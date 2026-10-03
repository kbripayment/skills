#!/usr/bin/env python3
"""
PDF 논문(p.14~51)에서 Abstract → Introduction → Methods → Results(Figure별 분할) → Discussion
순서로 Slack DM에 순차 전송. Results는 Figure subsection 단위로 쪼갬.
"""
import re
from pathlib import Path

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
env_path = "C:/Users/user/AppData/Local/hermes/.env"

# ── env 로드 ──
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

# ── PDF 본문(p.14~51)만 추출 ──
from pymupdf import open as fitz_open
doc = fitz_open(PDF_PATH)
pages = [doc[i].get_text() for i in range(13, 51)]
doc.close()
full = "\n".join(pages)

def section_pos(text, kw):
    for m in re.finditer(rf'(?<!\w){kw}(?!\w)', text):
        ctx = text[max(0,m.start()-80):m.start()+30]
        if any(x in ctx.lower() for x in ['see ', 'throughout the', 'revised', 'manuscript',
                'replaced', 'acknowledging', 'limitation in', 'discussion', 'in the',
                'please ', 'reviewer', 'comment', 'methods section']):
            continue
        return m.start()
    return None

abs_start = full.find("Background:")
if abs_start == -1:
    abs_start = section_pos(full, "Abstract")
intro_start = section_pos(full, "Introduction")
methods_start = section_pos(full, "Methods")
results_start = section_pos(full, "Results")
discussion_start = section_pos(full, "Discussion")
ref_start = section_pos(full, "References")

abstract = full[abs_start:abs_start+3500] if abs_start is not None else ""
intro = full[intro_start:methods_start] if intro_start is not None and methods_start is not None else ""
methods = full[methods_start:results_start] if methods_start is not None and results_start is not None else full[methods_start:] if methods_start is not None else ""
results = full[results_start:discussion_start] if results_start is not None and discussion_start is not None else full[results_start:ref_start] if results_start is not None and ref_start is not None else full[results_start:] if results_start is not None else ""
discussion = full[discussion_start:ref_start] if discussion_start is not None and ref_start is not None else full[discussion_start:] if discussion_start is not None else ""

print(f"Abstract: {len(abstract)}, Intro: {len(intro)}, Methods: {len(methods)}, Results: {len(results)}, Discussion: {len(discussion)}")

# ── Results를 Figure subsection 기준으로 분할 ──
# Known subsection 시작 키워드 (Figure 번호 순서로 정렬됨)
fig_markers = [
    ("Figure 1", ["Identification of metastasis-potential cells in primary breast"]),
    ("Figure 2", ["MPCs exhibit metastasis-associated transcriptional programs"]),
    ("Figure 3", ["Genomic evolution, cell state dynamics, and regulatory programs"]),
    ("Figure 4", ["MPCs are predicted to engage specific TME programs"]),
    ("Figure 5", ["Derivation and validation of an MPC-associated gene signature"]),
]

sup_fig_markers = [
    ("Supplementary Figure 3 (permutation)", ["To evaluate whether the retained RGSs showed"]),
    ("Supplementary Figure 10 (stability)", ["MPC identification was then repeated and compared"]),
    ("Supplementary Figure 14 (method comparison)", ["Consistent method-specific differences were also observed"]),
    ("Supplementary Figure 12 (CytoTRACE)", ["Consistently, MPCs showed significantly elevated cellular plasticity"]),
    ("Supplementary Figure 13 (MAGIC)", ["To evaluate the impact of MAGIC imputation"]),
]

all_markers = fig_markers + sup_fig_markers

def find_subsection(text, keywords):
    positions = []
    for kw in keywords:
        p = text.find(kw)
        if p != -1:
            positions.append((p, kw))
    if positions:
        positions.sort()
        return positions[0][0]
    return None

subsections = []
for label, kws in all_markers:
    pos = find_subsection(results, kws)
    if pos is not None:
        subsections.append((pos, label, kws))

subsections.sort(key=lambda x: x[0])

chunks = []
for i, (pos, label, kws) in enumerate(subsections):
    start = pos
    end = subsections[i+1][0] if i+1 < len(subsections) else len(results)
    txt = results[start:end].strip()
    if txt:
        chunks.append((label, txt))

if not chunks:
    chunks = [("Results (전체)", results)]

print(f"\nResults → {len(chunks)}개 subsection")
for lbl, t in chunks:
    print(f"  [{lbl}] {len(t)} chars")

# ── Slack 전송 ──
from slack_sdk.web import WebClient
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2400

def send(label, text, idx=0, total=1):
    lbl = label if total == 1 else f"{label} (파트 {idx+1}/{total})"
    msg = f"*{lbl}*\n\n{text}"
    if len(msg) <= MAX:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"  ✅ [{lbl}] → ts={resp['ts']}  ({len(msg)} chars)")
            return
        except Exception as e:
            print(f"  ❌ [{lbl}] → {e}")
            return
    # 길면 문단 단위로 분할
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    cur_lbl = label
    buf = ""
    buf_lbl = label
    for p in paras:
        trial = f"*{buf_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX and buf:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{buf_lbl}*\n\n{buf}", parse="mrkdwn")
                print(f"  ✅ [{buf_lbl}] → ts={resp['ts']}  ({len(buf)} chars)")
            except Exception as e:
                print(f"  ❌ [{buf_lbl}] → {e}")
            buf = p
            buf_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
            buf_lbl = cur_lbl
    if buf:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{buf_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"  ✅ [{buf_lbl}] → ts={resp['ts']}  ({len(buf)} chars)")
        except Exception as e:
            print(f"  ❌ [{buf_lbl}] → {e}")

print("\n=== 전송 시작 ===")
print("[1] Abstract"); send("Abstract", abstract[:3000])
print("[2] Introduction"); send("Introduction", intro[:3000])
print("[3] Methods"); send("Methods", methods[:3000])
print("[4] Results (Figure별)")
for i, (lbl, txt) in enumerate(chunks):
    send(lbl, txt[:3000], idx=i, total=len(chunks))
print("[5] Discussion"); send("Discussion", discussion[:3000])
print("\n=== 전송 완료 ===")
