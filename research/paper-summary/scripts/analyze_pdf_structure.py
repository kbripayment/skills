#!/usr/bin/env python3
"""
PDF 전체 구조 파악: 섹션/그림 경계 찾아서 인덱스까지 확인.
"""
import re
from pymupdf import open as fitz_open

PDF_PATH = "C:/Users/use 유저/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
# 실제 경로
PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"

doc = fitz_open(PDF_PATH)
print(f"총 페이지: {len(doc)}")

# 각 페이지 텍스트 수집 + 주요 마커 찾기
markers = {
    "Abstract": [],
    "Introduction": [],
    "Methods": [],
    "Results": [],
    "Discussion": [],
    "Figure": [],
    "References": [],
    "Supplementary": [],
}

for i in range(len(doc)):
    text = doc[i].get_text()
    for kw in markers:
        # "Figure 1", "Figure 2" 등 찾기
        if kw == "Figure":
            found = re.finditer(r'Figure\s+\d+[.:\-]?\s', text)
            for m in found:
                markers[kw].append((i+1, m.group().strip(), m.start()))
        elif kw in ("Abstract","Introduction","Methods","Results","Discussion","References"):
            found = re.finditer(rf'\b{kw}\b', text, re.IGNORECASE)
            for m in found:
                markers[kw].append((i+1, m.group(), m.start()))
        elif kw == "Supplementary":
            found = re.finditer(rf'\bSupplementary\b', text, re.IGNORECASE)
            for m in found:
                markers[kw].append((i+1, m.group(), m.start()))

for kw, locs in markers.items():
    if locs:
        print(f"\n--- {kw} ({len(locs)}개) ---")
        for page, match, pos in locs[:20]:
            snippet = doc[page-1].get_text()[max(0,pos-20):pos+60].replace('\n',' ').strip()
            print(f"  p.{page:3d}: \"{match}\"  [{snippet[:80]}]")

doc.close()
