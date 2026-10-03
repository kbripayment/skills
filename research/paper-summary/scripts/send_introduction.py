#!/usr/bin/env python3
"""Abstract 다음, Methods 이전의 Introduction 부분을 Slack에 전송."""
import re
from pymupdf import open as fitz_open

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
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

doc = fitz_open(PDF_PATH)
pages = [doc[i].get_text() for i in range(13, 51)]
doc.close()
full = "\n".join(pages)

abs_pos = full.find("Background:")

# Abstract 다음부터 Methods(문서상 "Methods" 위치 7572) 이전까지의 내용
intro_start = abs_pos + 3500
intro_end = full.find("Methods", intro_start)
if intro_end == -1:
    intro_end = 7572

intro_text = full[intro_start:intro_end].strip()
print(f"Introduction: {len(intro_text)} chars")
print(f"시작: {intro_text[:150]}")
print(f"끝: {intro_text[-150:]}")

from slack_sdk.web import WebClient
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2400

def slack_send(label, text):
    if not text.strip():
        print(f"  ⚠️ [{label}] 빈 텍스트")
        return
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"  ✅ [{label}] ts={resp['ts']}  ({len(msg)} chars)")
        except Exception as e:
            print(f"  ❌ [{label}] {e}")
        return
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    lbl = label
    buf = ""
    for p in paras:
        trial = f"*{lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX and buf:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{lbl}*\n\n{buf}", parse="mrkdwn")
                print(f"  ✅ [{lbl}] ts={resp['ts']}  ({len(buf)} chars)")
            except Exception as e:
                print(f"  ❌ [{lbl}] {e}")
            buf = p
            lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"  ✅ [{lbl}] ts={resp['ts']}  ({len(buf)} chars)")
        except Exception as e:
            print(f"  ❌ [{lbl}] {e}")

slack_send("Introduction", intro_text[:3000])
print("\n=== 전송 완료 ===")
