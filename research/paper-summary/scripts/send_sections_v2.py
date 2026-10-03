#!/usr/bin/env python3
"""PDF 논문 본문에서 섹션 경계를 정밀하게 찾아 Introduction, Methods, Figure 5 나머지, Discussion 전송."""
import re
from pathlib import Path

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

from pymupdf import open as fitz_open
doc = fitz_open(PDF_PATH)
# p.14~51 (0-indexed 13~50)
pages_text = []
for i in range(13, 51):
    pages_text.append(doc[i].get_text())
doc.close()

full = "\n".join(pages_text)

# ── Abstract 찾기 ──
abs_pos = full.find("Background:")
if abs_pos == -1:
    abs_pos = full.find("Abstract")
print(f"Abstract 위치: {abs_pos}")

# ── Methods 섹션 찾기 (Abstract 이후, "Methods"가 독립 섹션 제목으로 등장하는 곳) ──
# Abstract 내의 "Methods:" (one-liner) 제외 필요
methods_candidates = []
for m in re.finditer(r'\bMethods\b', full):
    ctx = full[max(0,m.start()-100):m.start()+100]
    # Abstract 내 one-liner: "Methods: We present..." 패턴 제외
    if re.search(r'Background:.*?Methods:.*?(?=Results:|Discussion:|$)', full[max(0,m.start()-500):m.start()+500], re.DOTALL):
        continue
    # "see Methods", "in the Methods" 등 제외
    ctx_low = ctx.lower()
    if any(x in ctx_low for x in ['see methods', 'in the methods section', 'methods section',
                                     'revised methods', 'methods description', 'methods and',
                                     'methods. we', 'methods, we', 'methods,']):
        continue
    methods_candidates.append(m.start())

print(f"Methods 후보: {methods_candidates}")

# ── Results 섹션 찾기 ──
results_candidates = []
for m in re.finditer(r'\bResults\b', full):
    ctx = full[max(0,m.start()-100):m.start()+100]
    ctx_low = ctx.lower()
    # Abstract 내 one-liner 제외
    if re.search(r'Background:.*?Results:.*?(?=Discussion:|$)', full[max(0,m.start()-500):m.start()+500], re.DOTALL):
        continue
    if any(x in ctx_low for x in ['see results', 'in the results', 'results section',
                                     'revised results', 'results and', 'results. we',
                                     'results of']):
        continue
    results_candidates.append(m.start())

print(f"Results 후보: {results_candidates}")

# ── Discussion 섹션 찾기 ──
disc_candidates = []
for m in re.finditer(r'\bDiscussion\b', full):
    ctx = full[max(0,m.start()-100):m.start()+100]
    ctx_low = ctx.lower()
    if any(x in ctx_low for x in ['see discussion', 'in the discussion', 'discussion section',
                                     'revised discussion', 'discussion and', 'discussion. we',
                                     'acknowledging', 'limitation in the discussion']):
        continue
    disc_candidates.append(m.start())

print(f"Discussion 후보: {disc_candidates}")

# ── References 찾기 ──
ref_candidates = []
for m in re.finditer(r'\bReferences\b', full):
    ctx = full[max(0,m.start()-50):m.start()+50]
    if 'Not applicable' in ctx:
        continue
    ref_candidates.append(m.start())

print(f"References 후보: {ref_candidates}")

# 섹션 결정: Abstract 이후의 첫 Methods, 첫 Results, 첫 Discussion, 첫 References 사용
abs_end = abs_pos + 3500 if abs_pos is not None else 0

methods_start = None
for c in methods_candidates:
    if c > abs_end:
        methods_start = c
        break

results_start = None
for c in results_candidates:
    if methods_start is not None and c > methods_start:
        results_start = c
        break
if results_start is None:
    for c in results_candidates:
        if c > abs_end:
            results_start = c
            break

disc_start = None
for c in disc_candidates:
    if results_start is not None and c > results_start:
        disc_start = c
        break

ref_start = None
for c in ref_candidates:
    if disc_start is not None and c > disc_start:
        ref_start = c
        break

# Introduction 찾기: Abstract 이후, Methods 이전의 첫 큰 섹션
intro_start = None
if methods_start is not None:
    between_abs_methods = full[abs_end:methods_start]
    # "Introduction" 찾기
    for m in re.finditer(r'\bIntroduction\b', between_abs_methods):
        ctx = between_abs_methods[max(0,m.start()-50):m.start()+50]
        ctx_low = ctx.lower()
        if any(x in ctx_low for x in ['see ', 'in the ', 'throughout the']):
            continue
        intro_start = abs_end + m.start()
        break

print(f"\n최종 섹션 위치:")
print(f"  Abstract: {abs_pos}")
print(f"  Introduction: {intro_start}")
print(f"  Methods: {methods_start}")
print(f"  Results: {results_start}")
print(f"  Discussion: {disc_start}")
print(f"  References: {ref_start}")

# 각 섹션 텍스트
abstract = full[abs_pos:abs_pos+3500] if abs_pos is not None else ""

intro = ""
if intro_start is not None:
    end = methods_start if methods_start is not None else results_start if results_start is not None else len(full)
    intro = full[intro_start:end]

methods = ""
if methods_start is not None:
    end = results_start if results_start is not None else disc_start if disc_start is not None else len(full)
    methods = full[methods_start:end]

results = ""
if results_start is not None:
    end = disc_start if disc_start is not None else ref_start if ref_start is not None else len(full)
    results = full[results_start:end]

discussion = ""
if disc_start is not None:
    end = ref_start if ref_start is not None else len(full)
    discussion = full[disc_start:end]

print(f"\n섹션 길이: Abstract={len(abstract)}, Intro={len(intro)}, Methods={len(methods)}, Results={len(results)}, Discussion={len(discussion)}")

# 이미 전송된 부분 체크
# Figure 5 subsection: "Derivation and validation of an MPC-associated gene signature"
fig5_marker = "Derivation and validation of an MPC-associated gene signature"
fig5_pos = results.find(fig5_marker) if results else -1
fig5_remaining = None
if fig5_pos >= 0:
    # 이미 약 3000자 전송됨
    fig5_remaining = results[fig5_pos+3000:]
    print(f"  Figure 5 위치: {fig5_pos}, 이미 전송: 3000, 남은: {len(fig5_remaining)} chars")

# Slack 전송
from slack_sdk.web import WebClient
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2400

def slack_send(label, text):
    if not text or not text.strip():
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

print("\n=== 전송 시작 ===")
print("[1] Introduction")
slack_send("Introduction", intro[:3000])
print("\n[2] Methods")
slack_send("Methods", methods[:3000])
print("\n[3] Figure 5 나머지")
if fig5_remaining:
    slack_send("Figure 5: Derivation and validation of an MPC-associated gene signature (나머지)", fig5_remaining[:4000])
print("\n[4] Discussion")
slack_send("Discussion", discussion[:3000])
print("\n=== 완료 ===")
