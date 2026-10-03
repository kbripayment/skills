#!/usr/bin/env python3
"""PDF에서 논문 본문(p.14~51)만 추출하여 섹션/그림 구조 파악."""
import re
from pymupdf import open as fitz_open

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
doc = fitz_open(PDF_PATH)

# 논문 본문: p.14 (인덱스 13) ~ p.51 (인덱스 50)
body_text = ""
for i in range(13, 51):
    body_text += doc[i].get_text() + "\n"

doc.close()

# 섹션 헤더 찾기 (페이지 번호/참조 노이즈 무시)
sections = {}
for kw in ["Abstract", "Introduction", "Methods", "Results", "Discussion", "References"]:
    # "Background:" 앞이나 단독 라인에 있는 것 우선
    for m in re.finditer(rf'(?<!\w){kw}(?!\w)', body_text):
        ctx = body_text[max(0,m.start()-40):m.start()+80].replace('\n',' ')
        # "see Abstract", "results청", rebuttal 등에서 나오는 것 필터링
        if any(x in ctx.lower() for x in ['see ', 'discussion', 'in the ', 'throughout', 'revised', 'manuscript', 'replaced', 'acknowledging', 'limitation in the']):
            continue
        sections.setdefault(kw, []).append((m.start(), ctx))
        if len(sections[kw]) >= 3:
            break

print("=== SECTION LOCATIONS ===")
for kw, locs in sections.items():
    print(f"\n[{kw}]")
    for pos, ctx in locs[:3]:
        print(f"  pos={pos:5d}  {ctx[:120]}")

# Results 내 Figure subsection 찾기
print("\n=== FIGURE SUBSECTIONS in Results ===")
fig_pat = re.compile(r'Figure\s+(\d+)[.:]\s+[A-Z]')
for m in fig_pat.finditer(body_text):
    ctx = body_text[max(0,m.start()-30):m.start()+120].replace('\n',' ')
    print(f"  pos={m.start():5d}  '{m.group()}'  {ctx[:150]}")

# Supplementary Figure subsection
print("\n=== SUPPLEMENTARY FIGURE SUBSECTIONS ===")
sup_fig_pat = re.compile(r'Supplementary\s+Figure\s+(\d+)[.:]\s+[A-Z]')
for m in sup_fig_pat.finditer(body_text):
    ctx = body_text[max(0,m.start()-30):m.start()+120].replace('\n',' ')
    print(f"  pos={m.start():5d}  '{m.group()}'  {ctx[:150]}")

# Results 섹션 range 확인
if "Results" in sections:
    results_start = sections["Results"][0][0]
    if "Discussion" in sections:
        results_end = sections["Discussion"][0][0]
    else:
        results_end = len(body_text)
    results_text = body_text[results_start:results_end]
    print(f"\n=== RESULTS SECTION: pos {results_start}~{results_end} ({len(results_text)} chars) ===")
    print(results_text[:800])
