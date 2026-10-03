#!/usr/bin/env python3
"""Discussion 섹션 위치를 정밀 탐색."""
import re
from pymupdf import open as fitz_open

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
doc = fitz_open(PDF_PATH)
pages_text = [doc[i].get_text() for i in range(13, 51)]
doc.close()

# 줄번호 제거
def remove_line_numbers(text):
    out = []
    for line in text.split('\n'):
        s = line.strip()
        if s.isdigit() and 1 <= int(s) <= 9999:
            continue
        out.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()

clean = remove_line_numbers("\n".join(pages_text))

# Find all "Discussion" occurrences with context
print("=== 'Discussion' 모든 출현 ===")
for m in re.finditer(r'\bDiscussion\b', clean):
    ctx_start = max(0, m.start()-60)
    ctx_end = m.start()+80
    ctx = clean[ctx_start:ctx_end].replace('\n', '|')
    print(f"  pos={m.start():6d}: ...{ctx}...")

# Methods/Results 섹션 위치를 먼저 찾고, 그 이후 첫 Discussion 찾기
methods_start = clean.find("Methods", 4000)
results_start = clean.find("Results", methods_start + 1000) if methods_start else -1
print(f"\nMethods 시작: {methods_start}")
print(f"Results 시작: {results_start}")

# Results 이후 "Discussion" 찾기 (Methods 내 "Discussion" 단어 배제)
if results_start > 0:
    after_results = clean[results_start:]
    for m in re.finditer(r'\bDiscussion\b', after_results):
        ctx_start = max(0, m.start()-60)
        ctx_end = m.start()+80
        ctx = after_results[ctx_start:ctx_end].replace('\n', '|')
        # Methods 안에서 "Discussion" 단어 쓰이는 패턴 제외
        # 예: "... in the Discussion ..." → Methods 안에서
        if 'in the Discussion' in ctx or 'see Discussion' in ctx or 'the Discussion' in ctx:
            print(f"  SKIP (Methods 내 Discussion): pos={results_start+m.start()}: {ctx}")
            continue
        print(f"  CANDIDATE Discussion pos={results_start+m.start()}: {ctx}")
