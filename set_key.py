import sys
key = sys.stdin.read().strip()
with open('/home/ubuntu/design-md-generator/.env', 'w') as f:
    f.write(f'OPENROUTER_KEY={key}\n')
print(f'Key saved ({len(key)} chars)')
