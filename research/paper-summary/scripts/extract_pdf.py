import fitz
doc = fitz.open("C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf")
print(f"페이지 수: {len(doc)}")
for i, page in enumerate(doc):
    text = page.get_text()
    if text.strip():
        print(f"\n=== 페이지 {i+1} ===")
        print(text[:3000])
