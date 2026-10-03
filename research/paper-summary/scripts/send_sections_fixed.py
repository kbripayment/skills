#!/usr/bin/env python3
"""PDF 본문에서 섹션을 정확히 찾아서 Slack에 전송 (원문 + Reviewer 코멘트)."""
import re
from pymupdf import open as fitz_open

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

# PDF 본문(p.14~51) 추출 후 줄번호 제거
doc = fitz_open(PDF_PATH)
pages_text = [doc[i].get_text() for i in range(13, 51)]
doc.close()

# 줄번호 제거: 단독 줄에 숫자만 있는 행 제거
def remove_line_numbers(text):
    out_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.isdigit() and 1 <= int(stripped) <= 9999:
            continue
        out_lines.append(line)
    cleaned = '\n'.join(out_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # 연속 빈 줄 → 2개
    return cleaned.strip()

clean_text = remove_line_numbers("\n".join(pages_text))

# ── 섹션 경계 찾기 ──
# Abstract: "Background:" 
abs_pos = clean_text.find("Background:")

# Methods: Abstract 이후 "Methods"가 별도 섹션 제목으로 등장하는 곳
# Methods 내에도 "Discussion" 단어가 나오므로, Methods 이후 첫 "Results" 찾아서 Methods 경계 확정
# 먼저 Methods 찾기: Abstract 직후 "Methods" (원고의 Methods 섹션 헤더)
methods_candidates = []
for m in re.finditer(r'\bMethods\b', clean_text):
    if m.start() > abs_pos + 3000:  # Abstract 이후
        ctx = clean_text[max(0,m.start()-100):m.start()+100]
        # Methods 섹션 헤더가 아닌 것 제외 (e.g. "Methods section", "see Methods", "in Methods")
        if any(x in ctx.lower() for x in ['see methods', 'in the methods', 'methods section',
                                            'methods. we', 'methods, we', 'methods,']):
            continue
        methods_candidates.append(m.start())
methods_start = methods_candidates[0] if methods_candidates else None

if methods_start is None:
    print("Methods 못 찾음 — exit")
    import sys; sys.exit(1)

# Results: Methods 이후 첫 "Results" 섹션 헤더
results_candidates = []
for m in re.finditer(r'\bResults\b', clean_text):
    if m.start() > methods_start + 500:
        ctx = clean_text[max(0,m.start()-100):m.start()+100]
        if any(x in ctx.lower() for x in ['see results', 'in the results', 'results section',
                                            'results. we', 'results, we', 'results,']):
            continue
        results_candidates.append(m.start())
results_start = results_candidates[0] if results_candidates else None

if results_start is None:
    print("Results 못 찾음 — exit")
    import sys; sys.exit(1)

# Discussion: Results 이후 첫 "Discussion" 섹션 헤더
disc_candidates = []
for m in re.finditer(r'\bDiscussion\b', clean_text):
    if m.start() > results_start + 500:
        ctx = clean_text[max(0,m.start()-100):m.start()+100]
        if any(x in ctx.lower() for x in ['see discussion', 'in the discussion', 'discussion section',
                                            'discussion. we', 'discussion, we', 'discussion,',
                                            'acknowledging', 'limitation in the discussion',
                                            'revised discussion']):
            continue
        disc_candidates.append(m.start())
discussion_start = disc_candidates[0] if disc_candidates else None

# Discussion 못 찾았으면 Results 끝난 이후 전체 텍스트를 Discussion으로
if discussion_start is None:
    # Methods에서 "Discussion"이라는 단어가 쓰인 경우를heuristic으로 건너뛴 후, 
    # Results 이후의 텍스트를 그대로 Discussion으로 사용
    print("  ⚠️ Discussion 섹션 헤더를 찾지 못함 — Results 이후 텍스트를 Discussion으로 사용")
    discussion_start = results_start + len(results_text)  # Results 직후부터

# References: Discussion 이후
ref_candidates = []
for m in re.finditer(r'\bReferences\b', clean_text):
    if m.start() > (discussion_start + 200 if discussion_start else results_start):
        ctx = clean_text[max(0,m.start()-50):m.start()+50]
        if 'Not applicable' in ctx:
            continue
        ref_candidates.append(m.start())
references_start = ref_candidates[0] if ref_candidates else None

print(f"섹션 위치:")
print(f"  Abstract: {abs_pos}")
print(f"  Methods: {methods_start}")
print(f"  Results: {results_start}")
print(f"  Discussion: {discussion_start}")
print(f"  References: {references_start}")

# 섹션별 텍스트
intro_text = ""  # Introduction은 Abstract 직후, Methods 이전의 내용
if methods_start:
    intro_text = clean_text[abs_pos+3500:methods_start] if abs_pos else clean_text[:methods_start]

methods_text = clean_text[methods_start:results_start] if methods_start and results_start else ""
results_text = clean_text[results_start:discussion_start] if results_start and discussion_start else ""
discussion_text = clean_text[discussion_start:references_start] if discussion_start and references_start else ""

print(f"\n섹션 길이: Intro={len(intro_text)}, Methods={len(methods_text)}, Results={len(results_text)}, Discussion={len(discussion_text)}")

# Results 맨 앞/뒤 확인
print(f"\nResults 시작 (처음 300자):\n{results_text[:300]}")
print(f"\n...\n")
print(f"Results 끝 (마지막 300자):\n{results_text[-300:]}")
print(f"\nDiscussion 시작 (처음 300자):\n{discussion_text[:300]}")

# ── Results를 Figure subsection으로 분할 ──
# Figure label 기준으로 boundaries 찾기
fig_submarkers = [
    ("Figure 1: Identification of metastasis-potential cells in primary breast Tumors using scMPC",
     ["Identification of metastasis-potential cells in primary breast"]),
    ("Supplementary Figure 3: RGS permutation null analysis",
     ["To evaluate whether the retained RGSs showed"]),
    ("Figure 2: MPCs exhibit metastasis-associated transcriptional programs across multiple biological dimensions",
     ["MPCs exhibit metastasis-associated transcriptional programs"]),
    ("Supplementary Figure 14: Method comparison",
     ["Consistent method-specific differences were also observed"]),
    ("Figure 3: Genomic evolution, cell state dynamics, and regulatory programs of MPCs",
     ["Genomic evolution, cell state dynamics, and regulatory programs"]),
    ("Figure 4: MPCs are predicted to engage specific TME programs",
     ["MPCs are predicted to engage specific TME programs"]),
    ("Figure 5: Derivation and validation of an MPC-associated gene signature",
     ["Derivation and validation of an MPC-associated gene signature"]),
    ("Supplementary Figure 10: MPC 식별 안정성 + 회귀 민감도 분석",
     ["MPC identification was then repeated and compared"]),
    ("Supplementary Figure 12: CytoTRACE2 분석",
     ["Consistently, MPCs showed significantly elevated cellular plasticity"]),
    ("Supplementary Figure 13: MAGIC imputation 영향 평가",
     ["To evaluate the impact of MAGIC imputation"]),
]

# subsection 위치 찾기 (순서대로)
subsections_with_pos = []
for label, keywords in fig_submarkers:
    for kw in keywords:
        pos = results_text.find(kw)
        if pos != -1:
            subsections_with_pos.append((pos, label))
            break

# 위치 순 정렬
subsections_with_pos.sort(key=lambda x: x[0])

# subsection 분할
subsections = []
for i, (pos, label) in enumerate(subsections_with_pos):
    start = pos
    end = subsections_with_pos[i+1][0] if i+1 < len(subsections_with_pos) else len(results_text)
    txt = results_text[start:end].strip()
    if txt:
        subsections.append((label, txt))

if not subsections:
    # fallback: Results 전체를 한 번에
    subsections = [("Results (전체)", results_text)]

print(f"\nResults → {len(subsections)}개 subsection:")
for label, txt in subsections:
    print(f"  [{label}] {len(txt)} chars")

# ── Slack 전송 ──
from slack_sdk.web import WebClient
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2300

def send(label, text):
    if not text.strip():
        print(f"  ⚠️ [{label}] 빈 텍스트")
        return
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"  ✅ [{label}] → ts={resp['ts']} ({len(msg)} chars)")
        except Exception as e:
            print(f"  ❌ [{label}] {e}")
        return
    # 긴 경우 문단 분할
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    cur_lbl = label
    buf = ""
    for p in paras:
        trial = f"*{cur_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX and buf:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
                print(f"  ✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
            except Exception as e:
                print(f"  ❌ [{cur_lbl}] {e}")
            buf = p
            cur_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"  ✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
        except Exception as e:
            print(f"  ❌ [{cur_lbl}] {e}")

print("\n" + "="*60)
print("SLACK 전송 시작")
print("="*60)

# 1. Abstract
print("\n[1/6] Abstract")
abstract = clean_text[abs_pos:abs_pos+3500] if abs_pos is not None else clean_text[:3500]
send("📄 Abstract (논문 원문)", abstract[:3000])

# 2. Introduction
print("\n[2/6] Introduction")
send("📄 Introduction (논문 원문)", intro_text[:3000])

# 3. Methods
print("\n[3/6] Methods")
send("📄 Methods (논문 원문)", methods_text[:3000])

# 4. Results (Figure별)
print(f"\n[4/6] Results ({len(subsections)}개 subsection)")
for label, txt in subsections:
    print(f"\n  → {label}")
    send(f"📄 Results — {label}", txt[:3000])

# 5. Discussion
print("\n[5/6] Discussion")
send("📄 Discussion (논문 원문)", discussion_text[:3000])

print("\n" + "="*60)
print("모든 섹션 전송 완료")
print("="*60)
