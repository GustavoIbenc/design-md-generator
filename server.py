#!/usr/bin/env python3
"""Design MD Generator — LLM-powered design extraction."""

import json
import re
import sys
import os
from html.parser import HTMLParser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse
from urllib.error import URLError
import ssl
import concurrent.futures

PORT = 8099
OPENROUTER_MODEL = "google/gemma-4-31b-it:free"

# Read API key: env var > .env file
OPENROUTER_KEY = os.environ.get('OPENROUTER_KEY', '')
if not OPENROUTER_KEY:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('OPENROUTER_KEY=') and len(line) > 20:
                    OPENROUTER_KEY = line.split('=', 1)[1]
                    break

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch_url(url, timeout=15):
    """Fetch URL directly with full browser headers."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }
    
    for _ in range(5):
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    url = resp.headers.get('Location', '')
                    if not url:
                        break
                    continue
                ct = resp.headers.get('Content-Type', '')
                if 'text' in ct or 'javascript' in ct or 'json' in ct or url.endswith(('.css', '.js')):
                    return resp.read().decode('utf-8', errors='replace')
                return ''
        except Exception as e:
            raise Exception(f"Failed to fetch {url}: {str(e)}")
    return ''


def extract_css_sources(html, base_url):
    """Find and fetch all CSS files + inline CSS."""
    css_sources = []

    # Inline <style> tags
    for m in re.finditer(r'<style[^>]*>([\s\S]*?)</style>', html, re.I):
        css_sources.append(m.group(1))

    # External <link rel="stylesheet"> URLs
    css_urls = []
    for m in re.finditer(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\']', html, re.I):
        css_urls.append(urljoin(base_url, m.group(1)))

    # Also check preload CSS
    for m in re.finditer(r'<link[^>]+rel=["\']preload["\'][^>]+href=["\']([^"\']+\.css)["\']', html, re.I):
        css_urls.append(urljoin(base_url, m.group(1)))

    # Fetch CSS files in parallel
    def fetch_css(url):
        try:
            return fetch_url(url, timeout=10)
        except:
            return ''

    if css_urls:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(fetch_css, css_urls))
            for css in results:
                if css:
                    css_sources.append(css)

    # Also fetch JS files that might contain CSS-in-JS (look for style/template literals)
    js_urls = []
    for m in re.finditer(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html, re.I):
        if 'polyfill' not in m.group(1) and 'webpack' not in m.group(1):
            js_urls.append(urljoin(base_url, m.group(1)))

    # Fetch a few JS files for CSS-in-JS patterns
    def fetch_js(url):
        try:
            content = fetch_url(url, timeout=8)
            if content and len(content) < 500000:
                return content[:100000]  # limit size
            return ''
        except:
            return ''

    if js_urls[:5]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(fetch_js, js_urls[:5]))
            for js in results:
                if js:
                    css_sources.append(js)

    return '\n'.join(css_sources)


def extract_design_tokens(all_css, html):
    """Extract design tokens from combined CSS sources."""
    tokens = {}

    # Colors
    colors = set()
    for m in re.finditer(r'#([0-9a-fA-F]{6})\b', all_css):
        colors.add('#' + m.group(1).lower())
    for m in re.finditer(r'#([0-9a-fA-F]{3})\b', all_css):
        h = m.group(1)
        colors.add('#' + h[0]*2 + h[1]*2 + h[2]*2)
    for m in re.finditer(r'rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)', all_css):
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        colors.add(f'#{r:02x}{g:02x}{b:02x}')
    for m in re.finditer(r'rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*([\d.]+)\s*\)', all_css):
        if float(m.group(4)) > 0.15:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            colors.add(f'#{r:02x}{g:02x}{b:02x}')

    # theme-color from meta
    tm = re.search(r'<meta[^>]*name=["\']theme-color["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    if tm:
        colors.add(tm.group(1).lower())

    boring = {'ffffff','f5f5f5','fafafa','f8f8f8','f0f0f0','eeeeee','e5e5e5','e0e0e0',
              '000000','111111','1a1a1a','222222','333333','444444','555555',
              '666666','777777','888888','999999','aaaaaa','bbbbbb','cccccc','dddddd'}
    tokens['colors'] = sorted(c for c in colors if c[1:] not in boring)

    # Fonts
    fonts = set()
    for m in re.finditer(r'font-family\s*:\s*([^;}]+)', all_css, re.I):
        first = m.group(1).split(',')[0].strip().strip('\'"')
        if first and not re.match(r'^(sans-serif|serif|monospace|cursive|fantasy|system-ui|inherit|initial|unset|revert)$', first, re.I):
            fonts.add(first)

    # Also check font preloads
    for m in re.finditer(r'<link[^>]+rel=["\']preload["\'][^>]+as=["\']font["\'][^>]+href=["\']([^"\']+)["\']', html, re.I):
        fname = re.search(r'/([^/]+?)\.[\w.]+$', m.group(1))
        if fname:
            name = fname.group(1).replace('-', ' ').replace('_', ' ').strip()
            if name not in ('woff', 'woff2', 'ttf', 'otf'):
                fonts.add(name)

    tokens['fonts'] = sorted(fonts)

    # Font sizes
    tokens['font_sizes'] = {}
    for m in re.finditer(r'font-size\s*:\s*([\d.]+(?:px|rem|em|%|vw))', all_css, re.I):
        s = m.group(1)
        tokens['font_sizes'][s] = tokens['font_sizes'].get(s, 0) + 1

    # Font weights
    tokens['font_weights'] = {}
    for m in re.finditer(r'font-weight\s*:\s*(\d{3}|bold|normal)', all_css, re.I):
        w = m.group(1)
        tokens['font_weights'][w] = tokens['font_weights'].get(w, 0) + 1

    # Line heights
    tokens['line_heights'] = {}
    for m in re.finditer(r'line-height\s*:\s*([\d.]+(?:px|rem|em|%)?)', all_css, re.I):
        tokens['line_heights'][m.group(1)] = tokens['line_heights'].get(m.group(1), 0) + 1

    # Letter spacing
    tokens['letter_spacings'] = {}
    for m in re.finditer(r'letter-spacing\s*:\s*([-\d.]+(?:px|rem|em)?)', all_css, re.I):
        tokens['letter_spacings'][m.group(1)] = tokens['letter_spacings'].get(m.group(1), 0) + 1

    # Shadows
    tokens['shadows'] = set()
    for m in re.finditer(r'box-shadow\s*:\s*([^;}]+)', all_css, re.I):
        v = m.group(1).strip()
        if v != 'none' and len(v) < 200:
            tokens['shadows'].add(v)
    tokens['shadows'] = sorted(tokens['shadows'])

    # Border radius
    tokens['radii'] = {}
    for m in re.finditer(r'border-radius\s*:\s*([^;}]+)', all_css, re.I):
        v = m.group(1).strip()
        if v != '0':
            tokens['radii'][v] = tokens['radii'].get(v, 0) + 1

    # Spacing
    tokens['spacings'] = {}
    for m in re.finditer(r'(?:gap|row-gap|column-gap|padding|margin)(?:-(?:top|bottom|left|right))?\s*:\s*([\d.]+(?:px|rem|em))\b', all_css, re.I):
        tokens['spacings'][m.group(1)] = tokens['spacings'].get(m.group(1), 0) + 1

    # Border widths
    tokens['border_widths'] = {}
    for m in re.finditer(r'border(?:-(?:top|bottom|left|right))?\s*:\s*([\d.]+(?:px|rem|em))\s+(?:solid|dashed|dotted)', all_css, re.I):
        tokens['border_widths'][m.group(1)] = tokens['border_widths'].get(m.group(1), 0) + 1

    # Max width
    tokens['max_widths'] = {}
    for m in re.finditer(r'max-width\s*:\s*([\d.]+(?:px|rem|em))', all_css, re.I):
        tokens['max_widths'][m.group(1)] = tokens['max_widths'].get(m.group(1), 0) + 1

    # Transitions
    tokens['transitions'] = set()
    for m in re.finditer(r'transition\s*:\s*([^;}]+)', all_css, re.I):
        v = m.group(1).strip()
        if v != 'none' and len(v) < 150:
            tokens['transitions'].add(v)
    tokens['transitions'] = sorted(tokens['transitions'])

    # CSS custom properties (variables)
    tokens['css_vars'] = {}
    for m in re.finditer(r'--([a-zA-Z][\w-]*)\s*:\s*([^;]+)', all_css):
        tokens['css_vars'][m.group(1)] = m.group(2).strip()

    return tokens


def call_llm(tokens, url, timeout=120):
    """Call LLM with extracted tokens — generate rich markdown like getdesign.md."""
    # Filter css_vars to only color-like ones for the prompt
    color_vars = {k: v for k, v in tokens.get('css_vars', {}).items()
                  if any(x in k.lower() for x in ['color', 'bg', 'text', 'accent', 'primary', 'border', 'surface'])}

    # Create compact token summary for LLM
    compact = {
        "colors": tokens["colors"][:40],
        "fonts": tokens["fonts"],
        "font_sizes": dict(sorted(tokens["font_sizes"].items(), key=lambda x: -x[1])[:12]),
        "font_weights": tokens["font_weights"],
        "line_heights": dict(sorted(tokens["line_heights"].items(), key=lambda x: -x[1])[:6]),
        "letter_spacings": dict(sorted(tokens["letter_spacings"].items(), key=lambda x: -x[1])[:6]),
        "shadows": tokens["shadows"][:8],
        "radii": dict(sorted(tokens["radii"].items(), key=lambda x: -x[1])[:10]),
        "spacings": dict(sorted(tokens["spacings"].items(), key=lambda x: -x[1])[:15]),
        "border_widths": dict(sorted(tokens["border_widths"].items(), key=lambda x: -x[1])[:6]),
        "max_widths": dict(sorted(tokens["max_widths"].items(), key=lambda x: -x[1])[:5]),
        "transitions": tokens["transitions"][:5],
        "css_vars": {k: tokens["css_vars"][k] for k in list(tokens["css_vars"].keys())[:40]}
    }

    # Load prompt from file
    prompt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt.txt')
    with open(prompt_file) as f:
        prompt_template = f.read()

    # Use simple replacement instead of .format() to avoid curly brace conflicts
    prompt = prompt_template.replace('{url}', url).replace('{css_data}', json.dumps(compact, indent=2)[:8000])

    payload = json.dumps({
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8000,
        "temperature": 0.2
    }).encode()

    req = Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://design-md-generator.local",
            "X-Title": "Design MD Generator"
        }
    )

    with urlopen(req, timeout=timeout, context=ctx) as resp:
        data = json.loads(resp.read())

    content = data["choices"][0]["message"]["content"]

    # Clean up markdown fences if wrapped
    content = re.sub(r'^```markdown\s*\n', '', content)
    content = re.sub(r'\n```\s*$', '', content)

    return {"markdown": content}


def fallback_markdown(tokens, url):
    """CSS-only fallback when LLM fails — generate basic markdown."""
    domain = urlparse(url).netloc.replace('www.', '')
    colors_list = tokens["colors"][:15]
    fonts_list = tokens["fonts"][:5]
    spacings = sorted(tokens["spacings"].keys(), key=lambda x: -tokens["spacings"][x])[:12]
    radii = sorted(tokens["radii"].keys(), key=lambda x: -tokens["radii"][x])[:8]
    shadows = tokens["shadows"][:5]
    font_sizes = sorted(tokens["font_sizes"].items(), key=lambda x: -x[1])[:10]

    md = f"""# Design System: {domain}

> Extracted from {url}
> Powered by CSS analysis (LLM unavailable)

## Overview

Design system extracted from CSS tokens. For full analysis with design philosophy and component specs, ensure LLM is available.

## Colors

| Hex | Usage |
|-----|-------|
"""
    for c in colors_list:
        md += f"| `{c}` | |\n"

    md += f"""
## Typography

### Font Families

"""
    for f in fonts_list:
        md += f"- **{f}**\n"

    md += "\n### Font Sizes\n\n"
    for size, count in font_sizes:
        md += f"- `{size}` (used {count}x)\n"

    md += f"""
## Spacing System

### Scale

"""
    for s in spacings:
        md += f"- `{s}`\n"

    md += f"""
## Borders & Radii

### Radius Scale

"""
    for r in radii:
        md += f"- `{r}`\n"

    md += f"""
## Elevation (Shadows)

"""
    for s in shadows:
        md += f"- `{s}`\n"

    md += """
## Known Gaps

- LLM unavailable — full design analysis not generated
- Component specifications not extracted
- Design philosophy not analyzed
- Responsive behavior not documented
"""

    return md


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(os.path.abspath(__file__)), **kwargs)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/analyze":
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                url = body.get("url", "")
                if not url.startswith("http"):
                    url = "https://" + url

                # Step 1: Fetch HTML
                try:
                    html = fetch_url(url)
                except Exception as fetch_err:
                    # Check if it's a 403/blocked error
                    err_str = str(fetch_err)
                    if '403' in err_str or 'Forbidden' in err_str:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "error": f"Site blocked: {url}. This site uses bot protection (Akamai/Cloudflare) that blocks cloud server IPs. Try a different URL.",
                            "url": url,
                            "_source": "error"
                        }).encode())
                        return
                    raise

                if not html or len(html) < 100:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "error": f"Site blocked: {url}. This site uses bot protection (Akamai/Cloudflare) that blocks cloud server IPs. Try a different URL or use the site's public design tokens.",
                        "url": url,
                        "_source": "error"
                    }).encode())
                    return

                # Step 2: Fetch CSS from external stylesheets + inline
                all_css = extract_css_sources(html, url)

                # Step 3: Extract tokens
                tokens = extract_design_tokens(all_css, html)

                # Step 4: LLM analysis
                try:
                    result = call_llm(tokens, url)
                    design = result["markdown"]
                    source = "llm"
                except Exception as e:
                    print(f"LLM failed: {e}", file=sys.stderr)
                    design = fallback_markdown(tokens, url)
                    source = "css_fallback"

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "markdown": design,
                    "url": url,
                    "_source": source
                }).encode())

            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"Design MD Generator — http://localhost:{PORT}")
    print(f"LLM: {OPENROUTER_MODEL}")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
