#!/usr/bin/env python3
"""PDF 논문 본문에서 Introduction, Methods, Figure 5 나머지, Discussion을 Slack에 전송."""
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
pages = [doc[i].get_text() for i in range(13, 51)]  # p.14~51
doc.close()
full = "\n".join(pages)

# 섹션 위치 다시 찾기
def sec_pos(text, kw):
    for m in re.finditer(rf'(?<!\w){kw}(?!\w)', text):
        ctx = text[max(0, m.start()-80):m.start()+30]
        if any(x in ctx.lower() for x in ['see ', 'throughout the', 'revised', 'manuscript',
                'replaced', 'acknowledging', 'limitation in', 'discussion', 'in the',
                'please ', 'reviewer', 'comment', 'methods section', 'rebuttal']):
            continue
        return m.start()
    return None

abs_start = full.find("Background:")
intro_start = sec_pos(full, "Introduction")
methods_start = sec_pos(full, "Methods")
results_start = sec_pos(full, "Results")
disc_start = sec_pos(full, "Discussion")
ref_start = sec_pos(full, "References")

# Introduction과 Methods가 sec_pos로 못 찾으면 document structure 확인
if intro_start is None:
    # Abstract 다음에 오는 첫 큰 섹션 찾기
    if abs_start is not None:
        after_abs = full[abs_start+3500:]
        # "Introduction" 대신 실제 원고 구조 확인
        intro_start = None
        for kw in ["Introduction", " 배경", "BACKGROUND"]:
            p = after_abs.find(kw)
            if p != -1:
                intro_start = abs_start + 3500 + p
                break

if methods_start is None and intro_start is not None:
    after_intro = full[intro_start+2000:]
    methods_start = None
    for kw in ["Methods", " METHODS", "방법"]:
        p = after_intro.find(kw)
        if p != -1:
            methods_start = intro_start + 2000 + p
            break

# Discussion 찾기 (rebuttal 외 실제 원고)
if disc_start is None:
    # Results 이후에 나오는 "Discussion"
    if results_start is not None:
        after_results = full[results_start+5000:]
        for kw in ["Discussion"]:
            p = after_results.find(kw)
            if p != -1:
                disc_start = results_start + 5000 + p
                break

# References도 찾기
if ref_start is None:
    if disc_start is not None:
        after_disc = full[disc_start+2000:]
        for kw in ["References", "REFERENCES"]:
            p = after_disc.find(kw)
            if p != -1:
                ref_start = disc_start + 2000 + p
                break
    elif results_start is not None:
        after_results = full[results_start+10000:]
        for kw in ["References", "REFERENCES"]:
            p = after_results.find(kw)
            if p != -1:
                ref_start = results_start + 10000 + p
                break

print(f"abs_start: {abs_start}")
print(f"intro_start: {intro_start}")
print(f"methods_start: {methods_start}")
print(f"results_start: {results_start}")
print(f"disc_start: {disc_start}")
print(f"ref_start: {ref_start}")

# 각 섹션 텍스트 준비
abstract = full[abs_start:abs_start+3500] if abs_start is not None else ""

intro = ""
if intro_start is not None:
    end = methods_start if methods_start is not None else (results_start if results_start is not None and results_start > intro_start else len(full))
    intro = full[intro_start:end]

methods = ""
if methods_start is not None:
    end = results_start if results_start is not None and results_start > methods_start else (disc_start if disc_start is not None and disc_start > methods_start else len(full))
    methods = full[methods_start:end]

results = ""
if results_start is not None:
    end = disc_start if disc_start is not None and disc_start > results_start else (ref_start if ref_start is not None and ref_start > results_start else len(full))
    results = full[results_start:end]

discussion = ""
if disc_start is not None:
    end = ref_start if ref_start is not None and ref_start > disc_start else len(full)
    discussion = full[disc_start:end]

print(f"\nAbstract: {len(abstract)} chars")
print(f"Introduction: {len(intro)} chars")
print(f"Methods: {len(methods)} chars")
print(f"Results: {len(results)} chars")
print(f"Discussion: {len(discussion)} chars")

# 이미 전송된 부분 확인 (Figure 5 subsection)
if results_start is not None:
    # Figure 5 subsection 위치 찾기
    fig5_marker = "Derivation and validation of an MPC-associated gene signature"
    fig5_pos = results.find(fig5_marker)
    if fig5_pos != -1:
        # 이미 전송된 부분: fig5_pos ~ fig5_pos+3000
        already_sent = 3000
        fig5_remaining = results[fig5_pos+already_sent:]
        print(f"\nFigure 5 subsection 위치: {fig5_pos} ~ {len(results)}")
        print(f"이미 전송된 부분: {already_sent} chars")
        print(f"남은 부분: {len(fig5_remaining)} chars")
    else:
        fig5_remaining = None
        print("\nFigure 5 subsection 못 찾음")

# Slack 전송
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2400

def send(label, text):
    if not text.strip():
        print(f"  ⚠️ [{label}] 빈 텍스트 - 건너뜀")
        return
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"  ✅ [{label}] → ts={resp['ts']}  ({len(msg)} chars)")
        except Exception as e:
            print(f"  ❌ [{label}] → {e}")
        return
    
    # 분할
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    cur_lbl = label
    buf = ""
    for p in paras:
        trial = f"*{cur_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX and buf:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
                print(f"  ✅ [{cur_lbl}] → ts={resp['ts']}  ({len(buf)} chars)")
            except Exception as e:
                print(f"  ❌ [{cur_lbl}] → {e}")
            buf = p
            cur_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"  ✅ [{cur_lbl}] → ts={resp['ts']}  ({len(buf)} chars)")
        except Exception as e:
            print(f"  ❌ [{cur_lbl}] → {e}")

print("\n=== 전송 시작 ===")
print("[Introduction]")
send("Introduction (재검토)", intro[:3000])
print("\n[Methods]")
send("Methods (재검토)", methods[:3000])
print("\n[Figure 5 나머지]")
if fig5_remaining:
    send("Figure 5: Derivation and validation of an MPC-associated gene signature (나머지)", fig5_remaining[:4000])
print("\n[Discussion]")
send("Discussion", discussion[:3000])
print("\n=== 전송 완료 ===")
