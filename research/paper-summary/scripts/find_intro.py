#!/usr/bin/env python3
"""PDF 원문에서 Introduction 영역 확인."""
import re
from pymupdf import open as fitz_open

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
doc = fitz_open(PDF_PATH)
pages = [doc[i].get_text() for i in range(13, 51)]  # p.14~51
doc.close()
full = "\n".join(pages)

# Abstract 위치
abs_pos = full.find("Background:")
print(f"Abstract 시작: {abs_pos}")

# Abstract 이후 ~ Methods 이전(7572)의 내용 확인
intro_region = full[abs_pos+3500:7572]
print(f"\n=== Abstract ~ Methods 사이 내용 ({len(intro_region)} chars) ===")
print(intro_region[:2000])
print(f"\n... 중간 생략 ...\n")
print(intro_region[-1000:])

# Methods 시작 부근도 확인
print(f"\n=== Methods 시작 부근 (7572 주변) ===")
print(full[7500:7700])
