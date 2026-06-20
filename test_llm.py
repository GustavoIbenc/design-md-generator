import json, re
from urllib.request import Request, urlopen
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# Read key from server.py
with open('server.py') as f:
    content = f.read()
key_match = re.search(r'OPENROUTER_KEY\s*=\s*"([^"]+)"', content)
key = key_match.group(1)

payload = json.dumps({
    "model": "google/gemma-4-31b-it:free",
    "messages": [{"role": "user", "content": 'Say hello in JSON: {"msg": "hello"}'}],
    "max_tokens": 100
}).encode()

req = Request("https://openrouter.ai/api/v1/chat/completions",
    data=payload,
    headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })

try:
    with urlopen(req, timeout=30, context=ctx) as resp:
        d = json.loads(resp.read())
        print("OK:", d["choices"][0]["message"]["content"][:200])
except Exception as e:
    print(f"ERROR: {e}")
