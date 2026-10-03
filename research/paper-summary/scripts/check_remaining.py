#!/usr/bin/env python3
"""현재 PDF 본문(p.14~51)에서 Results subsection들을 다시 정확히 추출."""
import re
from pymupdf import open as fitz_open

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
doc = fitz_open(PDF_PATH)
pages = [doc[i].get_text() for i in range(13, 51)]
doc.close()
full = "\n".join(pages)

def sec_pos(text, kw):
    for m in re.finditer(rf'(?<!\w){kw}(?!\w)', text):
        ctx = text[max(0,m.start()-80):m.start()+30]
        if any(x in ctx.lower() for x in ['see ', 'throughout the', 'revised', 'manuscript',
                'replaced', 'acknowledging', 'limitation in', 'discussion', 'in the',
                'please ', 'reviewer', 'comment', 'methods section']):
            continue
        return m.start()
    return None

results_start = sec_pos(full, "Results")
discussion_start = sec_pos(full, "Discussion")
ref_start = sec_pos(full, "References")

if discussion_start is None:
    discussion_start = ref_start if ref_start is not None else len(full)
elif ref_start is not None and ref_start < discussion_start:
    discussion_start = ref_start

results = full[results_start:discussion_start]
print(f"Results 범위: {results_start} ~ {discussion_start}  ({len(results)} chars)")
print(f"첫 300자: {results[:300]}")
print(f"\n마지막 300자: {results[-300:]}")

# subsection 재추출 (정확한 키워드 기반)
all_markers = [
    ("Figure 1: Identification of metastasis-potential cells", 
     ["Identification of metastasis-potential cells in primary breast"]),
    ("Supplementary Figure 3: permutation null analysis", 
     ["To evaluate whether the retained RGSs showed"]),
    ("Figure 2: MPCs exhibit metastasis-associated transcriptional programs", 
     ["MPCs exhibit metastasis-associated transcriptional programs"]),
    ("Supplementary Figure 14: method comparison", 
     ["Consistent method-specific differences were also observed"]),
    ("Figure 3: Genomic evolution, cell state dynamics, and regulatory programs", 
     ["Genomic evolution, cell state dynamics, and regulatory programs"]),
    ("Figure 4: MPCs are predicted to engage specific TME programs", 
     ["MPCs are predicted to engage specific TME programs"]),
    ("Figure 5: Derivation and validation of an MPC-associated gene signature", 
     ["Derivation and validation of an MPC-associated gene signature"]),
    ("Supplementary Figure 10: stability / regression sensitivity", 
     ["MPC identification was then repeated and compared"]),
    ("Supplementary Figure 12: CytoTRACE", 
     ["Consistently, MPCs showed significantly elevated cellular plasticity"]),
    ("Supplementary Figure 13: MAGIC imputation", 
     ["To evaluate the impact of MAGIC imputation"]),
]

found = []
for label, kws in all_markers:
    for kw in kws:
        p = results.find(kw)
        if p != -1:
            found.append((p, label, kw))
            break

found.sort(key=lambda x: x[0])
print(f"\n=== 찾은 subsection ({len(found)}개) ===")
for i, (pos, label, kw) in enumerate(found):
    end = found[i+1][0] if i+1 < len(found) else len(results)
    txt = results[pos:end].strip()
    print(f"\n[{i+1}] {label}")
    print(f"  위치: {pos} ~ {end}  ({len(txt)} chars)")
    print(f"  시작: {txt[:120].strip()}")
    print(f"  끝: {txt[-120:].strip()}")
