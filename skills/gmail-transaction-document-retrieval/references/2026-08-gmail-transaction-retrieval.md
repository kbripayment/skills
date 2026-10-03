# Verified Gmail retrieval pattern (2026-08 session)

## Search sequence

1. Parse the statement date and supplier from OCR or the statement itself.
2. Search vendor mail with `from:<vendor> after:<date-3> before:<date+45> has:attachment`.
3. Search exact transaction subjects and amounts, e.g. `subject:"2026-07-21" has:attachment` or `3828990 has:attachment`.
4. Search Hometax separately with `subject:전자세금계산서`, `subject:세금계산서`, and the supplier→buyer subject pattern.
5. Search inspection photos by exact date using `subject:검수사진` or `subject:"검수 사진"`.

## Confirmed attachment examples

- Vendor replies can include both a quote PDF and a tax-invoice PDF in one message.
- A Hometax message may have no PDF attachment but include `NTS_eTaxInvoice.html`; preserve the HTML source.
- Inspection-photo mail can have multiple images for a single date; retain the date-matched images only.

## Scanned-PDF lesson

A transaction statement may have zero native text and still yield usable Tesseract text. If the OCR-to-JSON stage returns an empty supplier/items result, do not stop. Use the supplier visible in OCR and the known vendor address to search Gmail directly.

## Verification requirements

For each downloaded artifact record:

- absolute output path
- byte size
- Gmail message ID
- sender and subject
- source attachment filename
- document type

If optional HTML→PDF rendering fails, report the failure but keep the original HTML attachment.
