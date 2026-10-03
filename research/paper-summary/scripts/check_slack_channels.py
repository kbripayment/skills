#!/usr/bin/env python3
import os, re

env_path = "C:/Users/user/AppData/Local/hermes/.env"
env = {}
with open(env_path, 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            env[key] = val

os.environ.update(env)

token = env.get('SLACK_BOT_TOKEN', '')
app_token = env.get('SLACK_APP_TOKEN', '')
print("BOT_TOKEN length:", len(token))
print("APP_TOKEN length:", len(app_token))

from slack_sdk.web import WebClient
c = WebClient(token=token)
me = c.auth_test()
print("BOT user:", me['user'])

chns = c.conversations_list(types='public_channel,private_channel', limit=100)
for ch in chns['channels']:
    print(f"  {ch['name']:30s} id={ch['id']}  members={ch.get('num_members')}  purpose={ch.get('purpose',{}).get('value','')}")
