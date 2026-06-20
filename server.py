#!/usr/bin/env python3
"""Design MD Generator - Analyze websites and generate design documentation."""

import json
import subprocess
import re
import sys
import os
import tempfile
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import threading

BROWSE_BIN = os.path.expanduser("~/.claude/skills/gstack/browse/dist/browse")
if not os.path.exists(BROWSE_BIN):
    BROWSE_BIN = os.path.expanduser("~/gstack/browse/dist/browse")

PORT = 8099


def run_browse(cmd_args, timeout=30):
    """Run a gstack browse command and return output."""
    try:
        result = subprocess.run(
            [BROWSE_BIN] + cmd_args,
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {e}"


def analyze_site(url):
    """Analyze a website's design using gstack browse."""
    result = {
        "url": url,
        "title": "",
        "colors": [],
        "fonts": [],
        "layout": {},
        "typography": {},
        "spacing": {},
        "components": [],
        "screenshots": {},
        "raw_css": "",
        "meta": {},
        "structure": ""
    }

    # 1. Navigate to the URL
    nav = run_browse(["goto", url], timeout=30)
    if "ERROR" in nav or "TIMEOUT" in nav:
        return {"error": f"Failed to load URL: {nav}"}

    # 2. Get page title
    title_output = run_browse(["js", "document.title"])
    result["title"] = title_output.strip('"\'') if title_output else ""

    # 3. Extract meta tags
    meta_js = """
    JSON.stringify({
        title: document.title,
        description: document.querySelector('meta[name="description"]')?.content || '',
        ogImage: document.querySelector('meta[property="og:image"]')?.content || '',
        themeColor: document.querySelector('meta[name="theme-color"]')?.content || '',
        viewport: document.querySelector('meta[name="viewport"]')?.content || ''
    })
    """
    meta_out = run_browse(["js", meta_js])
    try:
        result["meta"] = json.loads(meta_out)
    except:
        pass

    # 4. Extract all colors from computed styles
    colors_js = """
    (function() {
        const colors = new Set();
        const allElements = document.querySelectorAll('*');
        const props = ['color', 'background-color', 'border-color', 'border-top-color',
                       'border-bottom-color', 'border-left-color', 'border-right-color',
                       'box-shadow', 'text-shadow'];
        for (let i = 0; i < Math.min(allElements.length, 500); i++) {
            const el = allElements[i];
            const style = getComputedStyle(el);
            for (const prop of props) {
                const val = style.getPropertyValue(prop);
                if (val && val !== 'rgba(0, 0, 0, 0)' && val !== 'transparent' && val !== 'none') {
                    colors.add(val);
                }
            }
        }
        return JSON.stringify([...colors].slice(0, 50));
    })()
    """
    colors_out = run_browse(["js", colors_js])
    try:
        raw_colors = json.loads(colors_out)
        result["colors"] = raw_colors
    except:
        pass

    # 5. Extract fonts
    fonts_js = """
    (function() {
        const fonts = new Map();
        const allElements = document.querySelectorAll('*');
        for (let i = 0; i < Math.min(allElements.length, 300); i++) {
            const style = getComputedStyle(allElements[i]);
            const family = style.fontFamily;
            const size = style.fontSize;
            const weight = style.fontWeight;
            const lineHeight = style.lineHeight;
            const key = family;
            if (!fonts.has(key)) {
                fonts.set(key, {
                    family: family,
                    sizes: new Set(),
                    weights: new Set(),
                    lineHeights: new Set()
                });
            }
            const f = fonts.get(key);
            f.sizes.add(size);
            f.weights.add(weight);
            f.lineHeights.add(lineHeight);
        }
        const result = [];
        for (const [key, val] of fonts) {
            result.push({
                family: val.family,
                sizes: [...val.sizes].slice(0, 8),
                weights: [...val.weights].slice(0, 5),
                lineHeights: [...val.lineHeights].slice(0, 5)
            });
        }
        return JSON.stringify(result.slice(0, 15));
    })()
    """
    fonts_out = run_browse(["js", fonts_js])
    try:
        result["fonts"] = json.loads(fonts_out)
    except:
        pass

    # 6. Extract layout structure
    layout_js = """
    (function() {
        const body = document.body;
        const bodyStyle = getComputedStyle(body);
        const mainContainers = [];
        const directChildren = body.children;
        for (let i = 0; i < Math.min(directChildren.length, 20); i++) {
            const el = directChildren[i];
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            mainContainers.push({
                tag: el.tagName.toLowerCase(),
                class: el.className?.toString().slice(0, 80) || '',
                id: el.id || '',
                display: style.display,
                position: style.position,
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                padding: style.padding,
                margin: style.margin,
                gap: style.gap || 'none',
                gridTemplate: style.gridTemplateColumns !== 'none' ? style.gridTemplateColumns : '',
                flexWrap: style.flexWrap !== 'nowrap' ? style.flexWrap : '',
                children: el.children.length
            });
        }
        return JSON.stringify({
            bodyBg: bodyStyle.backgroundColor,
            bodyColor: bodyStyle.color,
            bodyFont: bodyStyle.fontFamily,
            bodyMaxWidth: bodyStyle.maxWidth,
            containers: mainContainers
        });
    })()
    """
    layout_out = run_browse(["js", layout_js])
    try:
        result["layout"] = json.loads(layout_out)
    except:
        pass

    # 7. Extract typography details
    typography_js = """
    (function() {
        const headings = [];
        for (let level = 1; level <= 6; level++) {
            const els = document.querySelectorAll('h' + level);
            for (let i = 0; i < Math.min(els.length, 3); i++) {
                const style = getComputedStyle(els[i]);
                headings.push({
                    level: level,
                    text: els[i].textContent.trim().slice(0, 50),
                    fontSize: style.fontSize,
                    fontWeight: style.fontWeight,
                    fontFamily: style.fontFamily.slice(0, 60),
                    color: style.color,
                    lineHeight: style.lineHeight,
                    letterSpacing: style.letterSpacing,
                    textTransform: style.textTransform
                });
            }
        }
        const paragraphs = [];
        const pEls = document.querySelectorAll('p');
        for (let i = 0; i < Math.min(pEls.length, 3); i++) {
            const style = getComputedStyle(pEls[i]);
            paragraphs.push({
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                fontFamily: style.fontFamily.slice(0, 60),
                color: style.color,
                lineHeight: style.lineHeight,
                letterSpacing: style.letterSpacing,
                maxWidth: style.maxWidth
            });
        }
        return JSON.stringify({headings: headings, paragraphs: paragraphs});
    })()
    """
    typo_out = run_browse(["js", typography_js])
    try:
        result["typography"] = json.loads(typo_out)
    except:
        pass

    # 8. Extract spacing patterns
    spacing_js = """
    (function() {
        const spacings = new Map();
        const els = document.querySelectorAll('section, article, main, header, footer, nav, div[class]');
        for (let i = 0; i < Math.min(els.length, 50); i++) {
            const style = getComputedStyle(els[i]);
            const key = style.padding + '|' + style.margin;
            if (!spacings.has(key)) {
                spacings.set(key, {
                    padding: style.padding,
                    margin: style.margin,
                    count: 0,
                    tag: els[i].tagName.toLowerCase()
                });
            }
            spacings.get(key).count++;
        }
        const result = [...spacings.values()]
            .sort((a, b) => b.count - a.count)
            .slice(0, 10);
        return JSON.stringify(result);
    })()
    """
    spacing_out = run_browse(["js", spacing_js])
    try:
        result["spacing"] = json.loads(spacing_out)
    except:
        pass

    # 9. Extract component patterns
    components_js = """
    (function() {
        const components = [];
        // Navigation
        const nav = document.querySelector('nav');
        if (nav) {
            const links = nav.querySelectorAll('a');
            components.push({
                type: 'navigation',
                links: links.length,
                style: {
                    display: getComputedStyle(nav).display,
                    position: getComputedStyle(nav).position,
                    bg: getComputedStyle(nav).backgroundColor
                }
            });
        }
        // Buttons
        const buttons = document.querySelectorAll('button, [role="button"], a[class*="btn"], a[class*="button"]');
        if (buttons.length > 0) {
            const first = buttons[0];
            const style = getComputedStyle(first);
            components.push({
                type: 'buttons',
                count: buttons.length,
                sample: {
                    bg: style.backgroundColor,
                    color: style.color,
                    borderRadius: style.borderRadius,
                    padding: style.padding,
                    fontSize: style.fontSize,
                    fontWeight: style.fontWeight,
                    textTransform: style.textTransform
                }
            });
        }
        // Cards
        const cards = document.querySelectorAll('[class*="card"], [class*="Card"]');
        if (cards.length > 0) {
            const first = cards[0];
            const style = getComputedStyle(first);
            components.push({
                type: 'cards',
                count: cards.length,
                sample: {
                    bg: style.backgroundColor,
                    borderRadius: style.borderRadius,
                    padding: style.padding,
                    boxShadow: style.boxShadow,
                    border: style.border
                }
            });
        }
        // Images
        const images = document.querySelectorAll('img');
        components.push({
            type: 'images',
            count: images.length,
            sample: images.length > 0 ? {
                borderRadius: getComputedStyle(images[0]).borderRadius,
                objectFit: getComputedStyle(images[0]).objectFit,
                width: getComputedStyle(images[0]).width
            } : null
        });
        return JSON.stringify(components);
    })()
    """
    comp_out = run_browse(["js", components_js])
    try:
        result["components"] = json.loads(comp_out)
    except:
        pass

    # 10. Get DOM structure overview
    structure_js = """
    (function() {
        function mapNode(el, depth) {
            if (depth > 3 || !el) return null;
            const style = getComputedStyle(el);
            const children = [];
            for (let i = 0; i < Math.min(el.children.length, 8); i++) {
                const child = mapNode(el.children[i], depth + 1);
                if (child) children.push(child);
            }
            return {
                tag: el.tagName.toLowerCase(),
                class: el.className?.toString().slice(0, 40) || '',
                display: style.display,
                children: children
            };
        }
        return JSON.stringify(mapNode(document.body, 0));
    })()
    """
    struct_out = run_browse(["js", structure_js])
    try:
        result["structure"] = json.loads(struct_out)
    except:
        pass

    # 11. Take screenshots
    for name, vp in [("desktop", "1280x720"), ("mobile", "375x812")]:
        run_browse(["viewport", vp])
        screenshot_path = f"/tmp/design-analysis-{name}.png"
        run_browse(["screenshot", screenshot_path])
        result["screenshots"][name] = screenshot_path

    # Reset viewport
    run_browse(["viewport", "1280x720"])

    return result


def rgb_to_hex(rgb_str):
    """Convert rgb(r, g, b) to #hex."""
    match = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', rgb_str)
    if match:
        r, g, b = match.groups()
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    match = re.search(r'rgba\((\d+),\s*(\d+),\s*(\d+)', rgb_str)
    if match:
        r, g, b = match.groups()
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    return rgb_str


def generate_markdown(data):
    """Generate a markdown design document from analysis data."""
    if "error" in data:
        return f"# Error\n\n{data['error']}"

    title = data.get("title", "Unknown Site")
    url = data.get("url", "")
    meta = data.get("meta", {})
    colors = data.get("colors", [])
    fonts = data.get("fonts", [])
    layout = data.get("layout", {})
    typography = data.get("typography", {})
    spacing = data.get("spacing", [])
    components = data.get("components", [])

    md = []
    md.append(f"# Design System: {title}")
    md.append(f"\n> Analyzed from [{url}]({url})")
    md.append(f"> Generated by Design MD Generator\n")

    # Meta
    if meta:
        md.append("## Site Info\n")
        if meta.get("description"):
            md.append(f"- **Description:** {meta['description']}")
        if meta.get("themeColor"):
            md.append(f"- **Theme Color:** `{meta['themeColor']}`")
        if meta.get("viewport"):
            md.append(f"- **Viewport:** `{meta['viewport']}`")
        md.append("")

    # Colors
    if colors:
        md.append("## Colors\n")
        md.append("### Primary Palette\n")
        # Categorize colors
        hex_colors = []
        for c in colors[:20]:
            h = rgb_to_hex(c)
            hex_colors.append(h)

        # Color table
        md.append("| Color | RGB Value |")
        md.append("|-------|-----------|")
        for c in colors[:15]:
            h = rgb_to_hex(c)
            md.append(f"| `{h}` | `{c}` |")
        md.append("")

        # CSS variables suggestion
        md.append("### Suggested CSS Variables\n")
        md.append("```css")
        md.append(":root {")
        for i, c in enumerate(colors[:8]):
            h = rgb_to_hex(c)
            var_name = ["--color-primary", "--color-secondary", "--color-accent",
                       "--color-bg", "--color-text", "--color-muted",
                       "--color-border", "--color-surface"][i] if i < 8 else f"--color-{i}"
            md.append(f"  {var_name}: {h};")
        md.append("}")
        md.append("```\n")

    # Typography
    if fonts:
        md.append("## Typography\n")
        for f in fonts[:5]:
            family = f.get("family", "unknown")
            sizes = ", ".join(f.get("sizes", [])[:5])
            weights = ", ".join(str(w) for w in f.get("weights", [])[:5])
            md.append(f"### `{family}`\n")
            md.append(f"- **Sizes:** {sizes}")
            md.append(f"- **Weights:** {weights}")
            md.append("")

        # Heading hierarchy
        headings = typography.get("headings", [])
        if headings:
            md.append("### Heading Hierarchy\n")
            md.append("| Level | Font Size | Weight | Color | Letter Spacing |")
            md.append("|-------|-----------|--------|-------|----------------|")
            for h in headings:
                md.append(f"| H{h['level']} | {h['fontSize']} | {h['fontWeight']} | `{rgb_to_hex(h.get('color', ''))}` | {h.get('letterSpacing', 'normal')} |")
            md.append("")

    # Layout
    if layout:
        md.append("## Layout\n")
        md.append(f"- **Body Background:** `{layout.get('bodyBg', 'N/A')}`")
        md.append(f"- **Body Color:** `{layout.get('bodyColor', 'N/A')}`")
        md.append(f"- **Body Font:** `{layout.get('bodyFont', 'N/A')}`")
        md.append(f"- **Max Width:** `{layout.get('bodyMaxWidth', 'N/A')}`")
        md.append("")

        containers = layout.get("containers", [])
        if containers:
            md.append("### Page Structure\n")
            md.append("```")
            for c in containers[:10]:
                tag = c.get("tag", "?")
                cls = c.get("class", "")[:30]
                display = c.get("display", "")
                w = c.get("width", "?")
                h = c.get("height", "?")
                md.append(f"<{tag}> .{cls}")
                md.append(f"  display: {display} | {w}x{h}px")
                if c.get("gridTemplate"):
                    md.append(f"  grid: {c['gridTemplate'][:60]}")
                if c.get("flexWrap") and c["flexWrap"] != "nowrap":
                    md.append(f"  flex-wrap: {c['flexWrap']}")
            md.append("```\n")

    # Spacing
    if spacing:
        md.append("## Spacing\n")
        md.append("| Pattern | Padding | Margin | Frequency |")
        md.append("|---------|---------|--------|-----------|")
        for s in spacing[:8]:
            md.append(f"| `{s.get('tag', '?')}` | `{s.get('padding', 'N/A')}` | `{s.get('margin', 'N/A')}` | {s.get('count', 0)} |")
        md.append("")

    # Components
    if components:
        md.append("## Components\n")
        for comp in components:
            ctype = comp.get("type", "unknown")
            md.append(f"### {ctype.title()}\n")
            if ctype == "navigation":
                md.append(f"- **Links:** {comp.get('links', 0)}")
                s = comp.get("style", {})
                md.append(f"- **Display:** `{s.get('display', 'N/A')}`")
                md.append(f"- **Position:** `{s.get('position', 'N/A')}`")
                md.append(f"- **Background:** `{s.get('bg', 'N/A')}`")
            elif ctype == "buttons":
                md.append(f"- **Count:** {comp.get('count', 0)}")
                s = comp.get("sample", {})
                if s:
                    md.append(f"- **Background:** `{s.get('bg', 'N/A')}`")
                    md.append(f"- **Color:** `{s.get('color', 'N/A')}`")
                    md.append(f"- **Border Radius:** `{s.get('borderRadius', 'N/A')}`")
                    md.append(f"- **Padding:** `{s.get('padding', 'N/A')}`")
                    md.append(f"- **Font Size:** `{s.get('fontSize', 'N/A')}`")
                    md.append(f"- **Font Weight:** `{s.get('fontWeight', 'N/A')}`")
                    md.append(f"- **Text Transform:** `{s.get('textTransform', 'none')}`")
            elif ctype == "cards":
                md.append(f"- **Count:** {comp.get('count', 0)}")
                s = comp.get("sample", {})
                if s:
                    md.append(f"- **Background:** `{s.get('bg', 'N/A')}`")
                    md.append(f"- **Border Radius:** `{s.get('borderRadius', 'N/A')}`")
                    md.append(f"- **Padding:** `{s.get('padding', 'N/A')}`")
                    md.append(f"- **Box Shadow:** `{s.get('boxShadow', 'N/A')}`")
            elif ctype == "images":
                md.append(f"- **Count:** {comp.get('count', 0)}")
                s = comp.get("sample")
                if s:
                    md.append(f"- **Border Radius:** `{s.get('borderRadius', 'N/A')}`")
                    md.append(f"- **Object Fit:** `{s.get('objectFit', 'N/A')}`")
            md.append("")

    # CSS Reference
    md.append("## CSS Reference\n")
    md.append("```css")
    md.append("/* Reset & Base */")
    md.append("* { margin: 0; padding: 0; box-sizing: border-box; }")
    if fonts:
        md.append(f"body {{ font-family: {fonts[0].get('family', 'sans-serif')}; }}")
    if layout.get("bodyBg"):
        md.append(f"body {{ background: {layout['bodyBg']}; color: {layout.get('bodyColor', '#000')}; }}")
    if layout.get("bodyMaxWidth") and layout["bodyMaxWidth"] != "none":
        md.append(f"main, .container {{ max-width: {layout['bodyMaxWidth']}; margin: 0 auto; }}")
    md.append("```")

    # Summary
    md.append("\n---")
    md.append(f"*Analysis complete. {len(colors)} colors, {len(fonts)} font families, {len(components)} component types detected.*")

    return "\n".join(md)


class DesignHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the design generator."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(os.path.join(os.path.dirname(__file__), "index.html"), "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/analyze":
            content_length = int(self.headers["Content-Length"])
            body = self.rfile.read(content_length)
            data = json.loads(body)
            url = data.get("url", "")

            if not url:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "No URL provided"}).encode())
                return

            # Ensure URL has protocol
            if not url.startswith("http"):
                url = "https://" + url

            # Analyze
            analysis = analyze_site(url)
            markdown = generate_markdown(analysis)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "markdown": markdown,
                "analysis": {
                    "colors": analysis.get("colors", []),
                    "fonts": analysis.get("fonts", []),
                    "title": analysis.get("title", ""),
                    "components": analysis.get("components", [])
                }
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logs


def main():
    # Check if browse binary exists
    if not os.path.exists(BROWSE_BIN):
        print(f"ERROR: browse binary not found at {BROWSE_BIN}")
        print("Run: cd ~/.claude/skills/gstack/browse && ./setup")
        sys.exit(1)

    print(f"Design MD Generator running on http://localhost:{PORT}")
    print(f"Using browse: {BROWSE_BIN}")
    server = HTTPServer(("0.0.0.0", PORT), DesignHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
