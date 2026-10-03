#!/usr/bin/env python3
"""Introduction 섹션을 Slack에 전송 (원문 + reviewer 의견 포함)."""
import re
from pymupdf import open as fitz_open
from slack_sdk.web import WebClient

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
methods_pos = full.find("Methods", abs_pos + 3500)
intro_text = full[abs_pos+3500:methods_pos].strip() if methods_pos != -1 else full[abs_pos+3500:abs_pos+5000]

print(f"Introduction: {len(intro_text)} chars")

# 2500자씩 나누어 전송
from slack_sdk.web import WebClient
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2400

def send(label, text):
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX:
        resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
        print(f"✅ {label}: ts={resp['ts']} ({len(msg)} chars)")
        return
    # 분할
    paras = re.split(r'\n\s*\n', text)
    buf = ""
    cur_lbl = label
    for p in paras:
        p = p.strip()
        trial = f"*{cur_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX and buf:
            resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"✅ {cur_lbl}: ts={resp['ts']} ({len(buf)} chars)")
            buf = p
            cur_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
        print(f"✅ {cur_lbl}: ts={resp['ts']} ({len(buf)} chars)")

# Introduction 원문 (clean)
intro_clean = intro_text.replace('\r\n', '\n').replace('\n\n\n', '\n\n')
send("📄 Introduction (논문 원문)", intro_clean[:3000])
