#!/usr/bin/env python3
"""PDF에서 abstract 부분만 추출 → Slack DM으로 전송."""
import re
from pathlib import Path

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
env_path = "C:/Users/user/AppData/Local/hermes/.env"

# env 로드
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

from pymupdf import open as fitz_open
doc = fitz_open(PDF_PATH)

# 1~3페이지에서 abstract 찾기
abstract_text = ""
for i in range(min(5, len(doc))):
    page = doc[i]
    text = page.get_text()
    if "Abstract" in text:
        idx = text.find("Abstract")
        chunk = text[idx:]
        intro_idx = chunk.find("Introduction")
        if intro_idx > 0:
            chunk = chunk[:intro_idx]
        abstract_text = chunk.strip()
        break

if not abstract_text:
    abstract_text = doc[0].get_text()[:3000]

doc.close()
print(f"Abstract 길이: {len(abstract_text)} chars")

from slack_sdk.web import WebClient
c = WebClient(token=env.get('SLACK_BOT_TOKEN', ''))
channel = "D0AMMSX1NQ2"

# Slack 메시지는 너무 길면 안 되니 적절히 나누기
MAX_MSG = 2500
parts = []
for i in range(0, len(abstract_text), MAX_MSG):
    parts.append(abstract_text[i:i+MAX_MSG])

for j, part in enumerate(parts):
    label = f"Abstract (파트 {j+1}/{len(parts)})" if len(parts) > 1 else "Abstract"
    msg = f"*{label}*\n\n{part}"
    resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
    print(f"✅ 파트 {j+1} 전송: ts={resp['ts']}")

print(f"\n총 {len(parts)}개 파트 전송 완료")
