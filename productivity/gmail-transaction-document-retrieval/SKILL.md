---
name: gmail-transaction-document-retrieval
category: productivity
description: Find Gmail transaction documents by vendor and date.
---

# Gmail Transaction Document Retrieval

Use this skill when a user asks to locate existing transaction documents in Gmail rather than generate a new request draft. The workflow is vendor/date/amount aware and preserves original attachments.

## Scope

Retrieve and verify, per transaction statement:

- 견적서 / quotation
- 전자세금계산서 / Hometax e-tax invoice
- 검수사진 / inspection photos

This skill complements, but does not replace, OCR-and-drafting skills that parse a statement and create a payment-request draft.

## Workflow

1. **Identify the transaction**
   - Confirm the exact statement filename, transaction date(s), supplier, vendor email, item names, and total amount if available.
   - For scanned PDFs, do not depend on PyMuPDF native text. Use Tesseract/PaddleOCR or inspect the statement enough to identify the supplier.

2. **Search Gmail first**

   **Count the work before choosing a route.** If the target set is small (roughly a dozen statements, a couple of vendors), read the statements directly with OCR/vision and drive Gmail yourself. Reach for `quote_tax_invoice_photo.py` when the batch is large enough that per-file LLM time dominates; otherwise the script's sequential provider fallback costs more wall-clock than the whole task. When every scripted provider is degraded at once, doing the extraction by hand is the correct response, not more retrying.
   - Do not treat same-folder filename matching as the primary search when the user asks to find existing documents.
   - Search vendor replies using the confirmed vendor address and a date window around the statement date:
     - `from:<vendor> after:YYYY/MM/DD before:YYYY/MM/DD has:attachment`
     - add `subject:결제`, `subject:견적`, item tokens, or the invoice amount when useful.
   - **Widen the window progressively (roughly ±2 weeks → ±6 weeks → ±3 months) and stop widening as soon as a supplier-matching hit appears.** A tight window around the statement date returns 0 hits in the normal case, because the invoice is issued after the goods are received and after a 결제 요청 thread — routinely 5–7 weeks later. Treat an empty tight-window result as "not issued yet", never as "does not exist".
   - Search Hometax separately:
     - `from:admin@example.go.kr after:... before:...`
     - `subject:전자세금계산서` or `subject:세금계산서`
     - use the supplier→buyer subject pattern and amount/item tokens for disambiguation.
   - Search inspection-photo mail separately with `subject:검수사진` or `subject:"검수 사진"`, constrained by the exact transaction date.
   - **When the statement's item name is abstract (a utility, a gas, a service), item-token matching returns nothing and the automated finder reports 0 photos.** Query the inspection sender directly and widen the date range to the whole statement span, then confirm each attachment by opening it — an inspection mail is almost never all one item type.
   - **Prefer exact-subject date keying over stamp OCR.** Inspection subjects are self-labelling — `7/9 검수사진 송부` — so `from:<sender> after:D-2 before:D+3 has:attachment` filtered to subjects starting with `N/M 검수사진` yields exactly the batch delivered on that date, with no OCR and no stamp ambiguity. The date window alone is not enough: it returns up to 7 mails (D-2 through D+2). The subject prefix is the actual key. Use this before any stamp-reading escalation.

2b. **Filter inspection photos by object, not by mail context.** A mail that mentions a gas supplier can carry gas cylinders *and* culture media in the same batch. Download the candidates and verify the physical object in each image before it enters the deliverable set; report what was excluded and why. When the user names a target object ("the big metal gas cylinders"), that image-level check is the deliverable, not a preliminary step.

3. **Score and verify candidates**
   - Prefer exact vendor, transaction date, item token, amount, and buyer-name matches.
   - If an automated matcher reports low confidence because supplier extraction failed, inspect the candidate mail list instead of declaring the document missing.
   - **Discard the automated top-1 whenever supplier extraction came back empty.** Keyword scoring is dominated by generic hits (전자세금계산서, 세금계산서, 결제) that every invoice mail shares, so an unanchored matcher promotes the same high-scoring mail for unrelated statements. Re-derive the match by hand from the supplier/date/items you extracted in step 1, and delete any file it already wrote.
   - Read candidates with `format="full"`. Metadata reads are the cheap way to list, but they are not reliable enough to source From/Subject/Date for matching decisions.
   - Record Gmail message ID, sender, subject, date, and attachment filename for every selected document.

4. **Download original attachments**
   - Save attachments into the requested folder with deterministic, readable names, e.g.:
     - `{date}_{item}_견적서_{vendor}.pdf`
     - `{date}_{item}_전자세금계산서_{vendor}.pdf`
     - `{date}_{item}_검수사진_{time}.jpg`
   - Preserve the original source extension and bytes. Do not delete or overwrite an HTML invoice while attempting PDF conversion.
   - Hometax messages may contain `NTS_eTaxInvoice.html` instead of a PDF. Save the HTML first; PDF rendering is optional.
   - Some vendors deliver the invoice through their own EDI portal mail with **no attachment at all** — the notice is the message body. Save the body as an `.html` artifact and label it a 도착안내/notice, not the invoice itself, so the report does not overstate what was retrieved.
   - **Rendering a portal page is not the same as retrieving the invoice.** When you follow an EDI link and screenshot or print-to-PDF the resulting web page, what you capture is the *portal UI* — 반송사유/승인/반송 buttons, `미승인 전자(세금)계산서` header, `승인 후 인쇄하시기 바랍니다` guidance — with the invoice table embedded below. Never name that capture `{...}_전자세금계산서.pdf`; it is a screenshot of a screen, and the user cannot tell it apart from the real document by filename. Either get the vendor's actual invoice file, or deliver the capture explicitly labelled as a portal-screen artifact and say in the report that the true tax-invoice document was not retrieved.

5. **Verify the result before reporting success**
   - **Prove the artifact, do not infer it from the code path.** A converter that returns bytes is not a converter that produced a document: `Page.printToPDF` and every `*_to_pdf_bytes` helper return a valid PDF for a page that rendered empty, and a 1 KB / 0-text file sails through existence and size checks. After every write, reopen the file and assert the content is there: extract text and require non-trivial length, and for image-based results confirm at least one embedded image. Only then report ✅.
   - Check every saved file exists and report its absolute path and byte size.
   - Report missing document types explicitly.
   - If PDF conversion fails because an optional renderer or helper module is unavailable, retain and report the original HTML attachment.
   - Distinguish **retrieved**, **rendered from a portal screen**, and **not found** in the final report. Collapsing the first two into one is how a wrong document gets presented as a success.

## Reusable implementation pattern

Use the existing Paperworks Gmail service and automation helper where available:

- Gmail service: `C:\Users\user\paperworks\tools\gmail_tool.py`
- Tax-invoice helper: `C:\Users\user\paperworks\tools\find_tax_invoice_for_statement.py`
- Integrated downloader: `C:\Users\user\AppData\Local\hermes\skills\productivity\automation\scripts\quote_tax_invoice_photo.py`

When `tools/` has no `__init__.py`, load modules with `importlib.util.spec_from_file_location` and register the expected module name in `sys.modules` before executing it. Also insert the package root on `sys.path` and register a synthetic `tools` package module, because the modules import each other by absolute name (`from tools.gmail_tool import …`, `from config import cfg`).

**Gmail service construction.** Build the service from the token file's own granted scopes — `Credentials.from_authorized_user_file(path)` with no `scopes` argument — rather than passing the module's hardcoded `SCOPES` list. A token issued with a narrower set than the code declares makes `creds.refresh()` fail with `invalid_scope`, and the read path does not need the extra scopes anyway. Persist the refreshed token back to the same file.

## Matching invoice mails to statements

See `references/hometax-and-edi-invoice-matching.md` for the disambiguation keys, why text extraction cannot read the Hometax HTML (and what to do instead), the retrieved/rendered/missing artifact table, and how to bootstrap the Paperworks modules.

## Finding inspection photos

See `references/inspection-photo-retrieval.md` for the query table to use when item-token matching returns nothing, the object-level filtering rule, and the stop condition for unresolved handwritten stamp dates.

## Hometax 보안메일 HTML 열기 (실전 절차)

홈택스 `NTS_eTaxInvoice.html`은 텍스트 파싱이 불가능하다. 내용은 `idCriPcContents` / `idCriAttachContents0` hidden input에 암호화되어 있고, 복호화는 `srtk.hometax.go.kr`의 외부 JS가 수행한다. 링크 추출/정규식으로 열려면 반드시 실제 브라우저가 필요하다.

1. ASCII 경로로 복사 (한글 파일명은 Chrome `file://` 로드 시 문제)
2. Chrome을 CDP로 기동:
   `"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9333 --user-data-dir="<ascii tmp>" --headless=new <file-url>`
3. `websocket-client`로 CDP 접속 (미설치 시 `pip install websocket-client`)
4. `Runtime.evaluate`로 `document.getElementById('idPcPwd').value='<PIN>'; InputPwd();`
5. 내용은 iframe `#CriMsgPosition`의 `contentDocument.body.innerText`에서 읽는다
6. `Page.printToPDF`로 PDF 저장 (셀카인드처럼 PNG 첨부가 있으면 `pymupdf.open(png).convert_to_pdf()`)

PIN 입력 후 `document.body.innerText`가 `인쇄 첨부보기`로 바뀌고 iframe 길이가 0이 아니면 정상 복호화된 것이다. PIN이 틀리면 이 상태로 넘어오지 않는다.

## 스마일EDI 세금계산서 (첨부 없음)

스마일EDI 메일에는 PDF 첨부가 없고 웹 링크만 있다. 링크는 `DtiEmail.do?taxid=<taxid>&...`.
사업자번호는 `input[name=inpasswd]`(type=password)에 넣고 폼을 submit해야 한다. 확인용 /sample연구소 번호 = 5148280611.

## 렌더 캡처 → PDF 변환 (빈 PDF 방지가 핵심)

`Page.printToPDF`는 **렌더링이 비어 있어도 유효한 PDF 바이트를 정상 반환한다.** DOM 높이가 낮게 잡힌 EDI 상세 페이지는 이 상태가 되며, 결과물은 텍스트 0자·약 1KB짜리 빈 파일이다. 파일이 생겼고 크기가 찍혔다는 사실은 유효성 증거가 아니다.

1. `Page.printToPDF` → 추출 텍스트 길이 검증 통과 시에만 채택
2. 실패 시 `Page.getLayoutMetrics()`로 `cssContentSize`를 얻고
   `Page.captureScreenshot(captureBeyondViewport=True, clip=..., scale=2)`로 캡처
3. PNG를 `pymupdf.open(png).convert_to_pdf()`로 PDF화
4. 최종 PDF에서 텍스트 또는 이미지 임베드를 확인한 뒤에만 사용자에게 보고

같은 폴백이 홈택스 렌더 경로에도 그대로 필요하다 — 변환기 하나만 고치면 다른 경로에서 같은 사고가 재발한다.

## Pitfalls

- **Reconcile the user's glob against the actual filenames before running.** Korean folder/type names get typo'd when dictated or transcribed — `*_고래명세서.pdf` for `*_거래명세서.pdf`, and similar consonant slips. A pattern matching zero files usually means a typo, not an empty folder: list the directory and match the request against real filenames, and say which files you selected rather than silently running a null search or silently substituting your own reading.
- **The user's path outranks the path you inferred.** A correction mid-task (`Y:\` when you assumed `Y:\ongoing\`) means the earlier search was run against the wrong tree and its "not found" results are void — re-glob the corrected path rather than carrying the earlier candidates forward. Confirm the file count each time so a wrong path cannot masquerade as an empty result.
- **The filename's item hint can lie about the contents.** A file named for an antibody can contain a lens-and-filter invoice on a later page. Read every page and report mixed-content files explicitly instead of attributing all pages to the filename.
- **Gmail's `attachments().get()` takes `id=`, not `attachmentId=`.** The attachment ID is the `id` argument; passing `attachmentId` raises `TypeError: Got an unexpected keyword argument` from the discovery layer, which reads like a library bug but is just the wrong kwarg.
- **Downscale before vision.** Large phone-resolution originals (4000px+) and multi-image montages both time out and return nothing. Resize so the longest edge is ~1100px, and batch two images per call at ~640px each rather than four at 900px. A timeout is a size problem until proven otherwise — re-check at reduced size before concluding the image is unreadable.
- A scanned transaction statement can produce `supplier=()` or zero structured items even when OCR text is usable. Supplement the supplier from OCR or the known vendor map and run a targeted Gmail query.
- **For the supplier header block, use `--psm 4` or `--psm 11`, not `--psm 6`.** These statements are table-structured, and psm 6's column assumptions shred the header into unreadable fragments — it can fail to yield 상호/사업자등록번호/이메일 on a page where psm 4 returns all three cleanly. When supplier extraction is the goal, crop the top ~32% of page 1 at ~400 dpi and run psm 4/11; reserve psm 6 for the item table.
- A statement file can cover **more than one transaction** — page 1 and page 2 carrying different dates, totals, and item lists. Read every page before assuming a single supplier/date/amount. When each page carries its own stamp date, that is a **multi-date statement**: retrieve a photo set per date and put each date's match on its own page of the deliverable PDF, labelled with that date. Do not emit one date's photos as the whole answer or merge both dates into a single unlabelled set.
- **Before filing "the code doesn't handle this", read the code and prove it.** Ask which module owns the behaviour, then grep for the parameter that carries it (e.g. `inspection_dates` threaded into the finder, or a per-date download wrapper) and confirm with a run log that shows both dates in the search key. Multi-date retrieval is often already implemented while the surrounding docs imply single-date handling; filing a requirement against implemented behaviour creates work that re-fixes a non-bug. Report "already handled, here is the log line that proves it" instead.
- Folder-level `has_existing_docs()` only detects same-folder filenames; it cannot prove that Gmail has no matching document.
- Hometax HTML is often a security mail attachment and may not contain a conventional PDF filename. Preserve the HTML source.
- The Hometax attachment is a *security-mail wrapper*, not a readable invoice: the payload is encrypted in hidden inputs, so every message's `NTS_eTaxInvoice.html` looks identical to text extraction (no amounts, no item names). Text extraction proves nothing — rank Hometax mails by the supplier name in the subject, issue date, and the item list in the vendor's own reply thread, and decrypt only the winner.
- **One Hometax mail is one tax invoice — never attach it to two statements.** When one supplier issued several statements, do not reuse the same message ID for more than one of them: the extraction succeeds, the PDF is a valid-looking document, and the second statement silently receives a clone of the first one's contents. The saved file even carries the right filename while listing the wrong item and amount. Detect this before extracting by hashing the encrypted payload (`idCriPcContents`, `idCriAttachContents0`): identical hashes across two HTMLs mean one mail, so the second statement has **no** invoice. Then confirm by comparing the extracted PDF's supplier/item/amount against the target statement — the approval number (e.g. `20261001-10261001-83988297`) is the per-document identifier. Delete the cloned PDF and say plainly that the invoice was never issued rather than leaving a mislabeled duplicate.
- A `미승인` marker on a portal page does not invalidate the invoice: Hometax transmission completes the next day regardless of buyer approval, so `미승인` and `국세청 전송 완료` legitimately coexist.
- A gas/utility supplier statement is a recurring-payment document spanning many delivery dates, so a single statement date will not match a single invoice. Check whether an open 미수금/추가 결제 request to that supplier is still pending before declaring the invoice missing.
- Inspection-photo messages can contain multiple unrelated photos. Match by exact date, sender/thread, and item context; do not download an entire broad search result without filtering.
- **A handwritten stamp date that reads differently at every zoom is not a date yet.** Cropping tighter or raising DPI past a certain point starts producing new readings rather than sharper ones; that is the signal to stop, not to try again. After two or three disagreeing passes, report the date-keyed candidate set and ask which page's date to match against. Re-cropping a field that has already given conflicting answers only burns turns.
- **Render and name the artifact only after asserting its content.** A headless print of an undecrypted Hometax HTML yields a valid, multi-page PDF that contains nothing but the PIN prompt — byte size and page count both look healthy, so existence checks pass and a wrong document gets reported as retrieved. Extract text and require an amount and a supplier before naming any render `_전자세금계산서.pdf`; a PIN-gate render is not an invoice.
- Always distinguish “candidate found but not confidently matched” from “no candidate found.”

## Session reference

See `references/2026-08-gmail-transaction-retrieval.md` for a verified search pattern and attachment examples from a Korean research-purchasing workflow.
