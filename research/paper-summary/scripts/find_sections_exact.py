#!/usr/bin/env python3
"""PDF 본문에서 실제 섹션 경계를 정밀하게 탐지."""
import re
from pymupdf import open as fitz_open

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
doc = fitz_open(PDF_PATH)
pages_text = [doc[i].get_text() for i in range(13, 51)]  # p.14~51
doc.close()
raw = "\n".join(pages_text)

# 줄번호 제거 (단독 줄에 있는 1~4자리 숫자)
def clean(text):
    lines = text.split('\n')
    out = []
    for line in lines:
        s = line.strip()
        if s.isdigit() and 1 <= int(s) <= 9999:
            continue
        out.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()

text = clean(raw)

# 섹션 찾기: "Discussion"이 Methods 안에 등장해도 무시하려면,
# Methods 이후에 "Discussion"이 *새 줄 시작 + 바로 뒤에 공백/숫자가 아닌 텍스트*로 오는 패턴 찾기.
# 또한 "Discussion"이 헤더일 때는 보통 "Discussion\n" 또는 "Discussion " 형태.

def find_header(text, keyword, after_pos=0):
    """keyword가 새 섹션 헤더로 등장하는 위치 찾기.
    헤더 직후의 패턴을 보고 판단."""
    for m in re.finditer(rf'(?<!\w){keyword}(?!\w)', text):
        pos = m.start()
        if pos < after_pos:
            continue
        # 헤더 직후 60자 확인
        after = text[pos+len(keyword):pos+len(keyword)+80]
        after_low = after.lower()
        # Methods 안에 있는 "Discussion" — 예: "... in the Discussion ..." 또는 "... Discussion section ..."
        # 헤더는 보통 Discussion 바로 뒤에 문장 시작 or 숫자(페이지)가 아닌 것
        if any(x in after_low for x in ['in the ', 'see ', 'the discussion', 'discussion section',
                                          'revised discussion', 'acknowledging', 'limitation in the']):
            continue
        # Discussion 헤더는 보통 공백 + 대문자 시작 문장 or 번호
        # 예외 필터링 끝, 헤더로 인정
        return pos
    return None

abs_start = text.find("Background:")
if abs_start == -1:
    abs_start = text.find("Abstract")

methods_start = None
for m in re.finditer(r'\bMethods\b', text):
    if m.start() > abs_start + 3500:
        ctx = text[m.start()-80:m.start()+80]
        if 'see methods' in ctx.lower() or 'in the methods' in ctx.lower():
            continue
        methods_start = m.start()
        break

results_start = None
for m in re.finditer(r'\bResults\b', text):
    if m.start() > (methods_start + 100 if methods_start else 0):
        ctx = text[m.start()-80:m.start()+80]
        if 'see results' in ctx.lower() or 'in the results' in ctx.lower():
            continue
        results_start = m.start()
        break

discussion_start = find_header(text, "Discussion", results_start + 200 if results_start else 0)

references_start = None
for m in re.finditer(r'\bReferences\b', text):
    if m.start() > (discussion_start + 100 if discussion_start else 0):
        ctx = text[m.start()-50:m.start()+50]
        if 'Not applicable' in ctx:
            continue
        references_start = m.start()
        break

print(f"Abstract: {abs_start}")
print(f"Methods: {methods_start}")
print(f"Results: {results_start}")
print(f"Discussion: {discussion_start}")
print(f"References: {references_start}")

# Methods 뒤 intro_start(after Methods 시작 전까지의 Methods 내용)
# Methods 이전: Abstract+Introduction 끝
intro_end = methods_start if methods_start else len(text)
intro_text = text[abs_start+3500:intro_end] if abs_start != -1 else ""

methods_text = ""
if methods_start and results_start:
    methods_text = text[methods_start:results_start]
elif methods_start:
    methods_text = text[methods_start:discussion_start] if discussion_start else text[methods_start:]

results_text = ""
if results_start:
    end = discussion_start if discussion_start else (references_start if references_start else len(text))
    results_text = text[results_start:end]

discussion_text = ""
if discussion_start:
    end = references_start if references_start else len(text)
    discussion_text = text[discussion_start:end]

print(f"\nIntro: {len(intro_text)} chars")
print(f"Methods: {len(methods_text)} chars")
print(f"Results: {len(results_text)} chars")
print(f"Discussion: {len(discussion_text)} chars")

# Results 텍스트 처음/끝
print(f"\nResults 첫 200자:\n{results_text[:200]}")
print(f"\nResults 마지막 200자:\n{results_text[-200:]}")
print(f"\nDiscussion 첫 200자:\n{discussion_text[:200]}")
