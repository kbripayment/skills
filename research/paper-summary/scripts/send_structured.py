#!/usr/bin/env python3
"""
PDF 논문 본문(p.14~51)에서 Abstract/Intro/Methods/Results/Discussion 추출,
Results는 Figure subsection별로 분할하여 Slack DM으로 순차 전송.
"""
import re, html
from pathlib import Path

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"

# ── env 로드 ──
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

# ── PDF에서 논문 본문 추출 (p.14~51, 0-indexed 13~50) ──
from pymupdf import open as fitz_open
doc = fitz_open(PDF_PATH)
pages_text = [doc[i].get_text() for i in range(13, 51)]  # p.14~51
doc.close()

full_body = "\n".join(pages_text)

# ── 섹션 경계 찾기 ──
def find_section_start(text, keyword):
    """본문 내에서 keyword가 단독 섹션 제목으로 등장하는 위치 찾기."""
    for m in re.finditer(rf'(?<!\w){keyword}(?!\w)', text):
        ctx = text[max(0, m.start()-60):m.start()+20]
        # Review/저자응답 문맥에서 나오는 것 제외
        ctx_lower = ctx.lower()
        if any(x in ctx_lower for x in ['see ', 'see also', 'in the ', 'throughout the',
                                          'revised', 'manuscript', 'replaced', 'acknowledging',
                                          'limitation in the', 'discussion', 'see methods',
                                          'please', 'reviewer', 'rebuttal', 'comment']):
            continue
        # Introduction 앞에 "Background:" 있는 원고 구조 확인
        pos = m.start()
        return pos
    return None

# Abstract: p.14 시작 ("Background:"로 시작하는 Abstract)
abstract_start = full_body.find("Background:")
if abstract_start == -1:
    abstract_start = find_section_start(full_body, "Abstract")
abstract_text = full_body[abstract_start:abstract_start+4000] if abstract_start is not None else ""

intro_start = find_section_start(full_body, "Introduction")
intro_text = ""
if intro_start is not None:
    methods_start = find_section_start(full_body, "Methods")
    if methods_start is None:
        methods_start = len(full_body)
    intro_text = full_body[intro_start:methods_start]

methods_start = find_section_start(full_body, "Methods")
results_start = find_section_start(full_body, "Results")
discussion_start = find_section_start(full_body, "Discussion")
references_start = find_section_start(full_body, "References")

methods_text = ""
if methods_start is not None and results_start is not None:
    methods_text = full_body[methods_start:results_start]
elif methods_start is not None:
    methods_text = full_body[methods_start:]

results_text = ""
if results_start is not None:
    end = discussion_start if discussion_start is not None else (references_start if references_start is not None else len(full_body))
    results_text = full_body[results_start:end]

discussion_text = ""
if discussion_start is not None:
    end = references_start if references_start is not None else len(full_body)
    discussion_text = full_body[discussion_start:end]

print(f"Abstract: {len(abstract_text)} chars")
print(f"Introduction: {len(intro_text)} chars")
print(f"Methods: {len(methods_text)} chars")
print(f"Results: {len(results_text)} chars")
print(f"Discussion: {len(discussion_text)} chars")

# ── Results 내 Figure subsection 분할 ──
# Figure subsection 순서는 Figure 1→5 순서에 맞춤.
# 각 subsection을 식별하는 시작 문장(생략 없이 전체 text에서 찾음).
figure_subsections = [
    ("Figure 1", [
        "Identification of metastasis-potential cells in primary breast",
    ]),
    ("Figure 2", [
        "MPCs exhibit metastasis-associated transcriptional programs",
        "MPCs exhibit metastasis-associated transcriptional",
    ]),
    ("Figure 3", [
        "Genomic evolution, cell state dynamics, and regulatory",
    ]),
    ("Figure 4", [
        "MPCs are predicted to engage specific TME programs",
    ]),
    ("Figure 5", [
        "Derivation and validation of an MPC-associated gene",
    ]),
]

# Supplementary Figure subsections도 Results 안에 산재됨
sup_figure_subsections = [
    ("Supplementary Figure 3 (permutation null)", [
        "To evaluate whether the retained RGSs showed performance beyond",
        "To evaluate whether the retained RGSs showed",
    ]),
    ("Supplementary Figure 10 (stability / regression)", [
        "MPC identification was then repeated and compared with the original",
        "MPC identification was then repeated",
    ]),
    ("Supplementary Figure 12 (CytoTRACE)", [
        "Consistently, MPCs showed significantly elevated cellular plasticity",
        "Consistently, MPCs showed significantly elevated",
    ]),
    ("Supplementary Figure 13 (MAGIC)", [
        "To evaluate the impact of MAGIC imputation",
        "To evaluate the impact of MAGIC",
    ]),
    ("Supplementary Figure 14 (method comparison)", [
        "Consistent method-specific differences were also observed",
    ]),
]

def find_subsection_pos(text, start_keywords):
    """text 내에서 start_keywords 중 하나로 시작하는 subsection 위치 찾기.
    가장 먼저 등장하는 것을 반환."""
    positions = []
    for kw in start_keywords:
        m = text.find(kw)
        if m != -1:
            positions.append((m, kw))
    positions.sort(key=lambda x: x[0])
    if positions:
        return positions[0][0]  # 가장 앞 위치
    return None

def split_results_by_figures(results_text):
    """Results 텍스트를 Figure subsection 기준으로 분할.
    반환: [(label, subsection_text), ...]
    subsections은 원본 text 순서대로 정렬.
    """
    # 모든 subsection 위치 수집
    sections_found = []
    for label, kws in figure_subsections + sup_figure_subsections:
        pos = find_subsection_pos(results_text, kws)
        if pos is not None:
            sections_found.append((pos, label, kws))
    
    if not sections_found:
        print("⚠️  어떤 subsection도 찾지 못함 - Results 전체 전송")
        return [("Results (전체)", results_text)]
    
    # 위치 순 정렬
    sections_found.sort(key=lambda x: x[0])
    
    # subsection 경계: 현재 subsection 시작부터 다음 subsection 시작 전까지
    result = []
    for i, (pos, label, kws) in enumerate(sections_found):
        start = pos
        if i + 1 < len(sections_found):
            end = sections_found[i + 1][0]
        else:
            end = len(results_text)
        subsection = results_text[start:end].strip()
        if subsection:
            result.append((label, subsection))
    
    return result

results_parts = split_results_by_figures(results_text)
print(f"\nResults → {len(results_parts)}개 subsection으로 분할:")
for label, txt in results_parts:
    print(f"  [{label}]  {len(txt)} chars")

# ── Slack 전송 ──
from slack_sdk.web import WebClient
c = WebClient(token=env.get('SLACK_BOT_TOKEN', ''))
channel = "D0AMMSX1NQ2"

MAX_MSG = 2500  # Slack 메시지 길이 제한 고려

def send_to_slack(label, text, part_idx=0, total_parts=1):
    """Slack에 전송. 긴 텍스트는 여러 메시지로 분할."""
    full_label = f"{label}" if total_parts == 1 else f"{label} (파트 {part_idx+1}/{total_parts})"
    msg = f"*{full_label}*\n\n{text}"
    
    # 너무 길면 분할
    if len(msg) > MAX_MSG:
        # 문단 단위로 분할 시도
        paragraphs = re.split(r'\n\s*\n', text)
        chunk = ""
        chunks = []
        for para in paragraphs:
            test = f"*{full_label}*\n\n" + chunk + para
            if len(test) > MAX_MSG and chunk:
                chunks.append((full_label, chunk.strip()))
                chunk = para
                full_label_parts = full_label.split(" ")
                # 새 chunk용 label은 마지막 파트 번호 표시
                full_label = f"{label} (계속)"
            else:
                chunk = (chunk + "\n\n" + para).strip() if chunk else para
        if chunk:
            chunks.append((full_label, chunk.strip()))
        
        for j, (lb, ch) in enumerate(chunks):
            send_msg = f"*{lb}*\n\n{ch}"
            try:
                resp = c.chat_postMessage(channel=channel, text=send_msg, parse="mrkdwn")
                print(f"  ✅ [{lb}] 전송: ts={resp['ts']}  ({len(send_msg)} chars)")
            except Exception as e:
                print(f"  ❌ [{lb}] 전송 실패: {e}")
    else:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"  ✅ [{label}] 전송: ts={resp['ts']}  ({len(msg)} chars)")
        except Exception as e:
            print(f"  ❌ [{label}] 전송 실패: {e}")

# ── 전송 순서: Abstract → Intro → Methods → Results(Figure별) → Discussion ──
print("\n=== SLACK 전송 시작 ===")

print("\n[1/5] Abstract 전송 중...")
send_to_slack("Abstract", abstract_text[:3000])

print("\n[2/5] Introduction 전송 중...")
send_to_slack("Introduction", intro_text[:3000])

print("\n[3/5] Methods 전송 중...")
send_to_slack("Methods", methods_text[:3000])

print("\n[4/5] Results 전송 중 (Figure별 분할)...")
for label, txt in results_parts:
    send_to_slack(label, txt[:3000])

print("\n[5/5] Discussion 전송 중...")
send_to_slack("Discussion", discussion_text[:3000])

print("\n=== 전송 완료 ===")
