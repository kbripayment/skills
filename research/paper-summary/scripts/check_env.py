import os
from pathlib import Path

home = Path(r'C:\Users\user')
target = Path(r'C:\Users\user\AppData\Local\hermes\skills\research\paper-summary\scripts')

print('home listing error detection:')
try:
    items = list(home.iterdir())
    print(f'  {len(items)} items')
except Exception as e:
    print(f'  ERROR: {e}')

print('\ntarget listing:')
try:
    items = list(target.iterdir())
    print(f'  {len(items)} items')
    for it in items:
        print(f'  {it.name}')
except Exception as e:
    print(f'  ERROR: {e}')

print('\nsending slack check:')
# env 로드
env_path = Path(r'C:\Users\user\AppData\Local\hermes\.env')
env = {}
with open(env_path, 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        import re
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            env[key] = val

from slack_sdk.web import WebClient
c = WebClient(token=env.get('SLACK_BOT_TOKEN',''))
try:
    resp = c.chat_postMessage(channel='D0AMMSX1NQ2', text='Slack 연결 확인 ✅')
    print(f'Slack OK: ts={resp[\"ts\"]}')
except Exception as e:
    print(f'Slack FAIL: {e}')
