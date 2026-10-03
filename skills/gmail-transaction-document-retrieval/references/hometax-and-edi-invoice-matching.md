# Hometax and EDI invoice matching

How to decide that a Gmail e-tax-invoice notice actually belongs to a given
transaction statement, and what each source of truth can and cannot tell you.

## Sources of the invoice, ranked by trust

1. **Vendor's own PDF** attached to a 지급신청/결제 thread, e.g.
   `{date}_{item}_전자세금계산서{amount}.pdf`. Richest source: item names and
   amounts are extractable. Prefer it.
2. **Vendor EDI notice** (스마일EDI and similar). The subject names the supplier,
   the body may carry the item table. Often **no attachment** — save the body.
3. **Hometax notice** from `admin@example.go.kr`. Subject carries
   `공급자->공수신자` and an issue date. That is the entire usable payload.

## Why the Hometax attachment yields nothing to text extraction

`NTS_eTaxInvoice.html` is a Hometax *보안메일* wrapper. Its content sits in
`idCriPcContents` / `idCriAttachContents0` hidden inputs, base64+AES encrypted,
and the decryptor is external JS on `srtk.hometax.go.kr`. Therefore:
- no amounts, no item names, no issue date survive regex or HTML-to-text
- every message's file is near-identical boilerplate plus a different encrypted blob
- text extraction can neither confirm nor reject a candidate

This is an *access* problem, not a data-absence problem. The invoice data is
fully present in the file — you need a real browser plus the PIN to reach it
(see the Hometax section in SKILL.md). Do not conclude "Hometax mails carry no
usable payload"; conclude "text extraction cannot read them".

Cheap triage first: the **subject** (`공급자->공수신자`) and the **body** alone
are enough to rank Hometax candidates by supplier and issue date. Decrypt only
the one you intend to keep, rather than every hit.

## Distinguishing the three retrievable artifacts

Getting a tax invoice can end in three materially different states, and they
must never be reported with the same confidence:

| State | What you have | Filename | Report as |
|---|---|---|---|
| Retrieved | the vendor's actual invoice file | `{date}_{vendor}_전자세금계산서.pdf` | ✅ found |
| Rendered | a capture of an EDI portal page | `{date}_{vendor}_세금계산서_화면캡처.pdf` | ⚠️ portal screen, document not retrieved |
| Missing | nothing | — | ❌ not found |

A portal capture is recognisable in its content: 반송사유/승인/반송 buttons, a
`미승인 전자(세금)계산서` header, and `승인 후 인쇄하시기 바랍니다`. It also
displays a *correct* 합계금액, so amount-matching alone will accept it — the
distinguishing signal is the surrounding UI chrome, not the totals.

Relatedly, `미승인` on a portal page does not mean the invoice is invalid:
Hometax transmission completes the next day regardless of buyer approval, so
`미승인` and `국세청 전송 완료` legitimately coexist.

## Headless print-to-PDF of the Hometax HTML proves nothing

`msedge --headless --print-to-pdf` (or the same via `Page.printToPDF`) on an
undecrypted `NTS_eTaxInvoice.html` returns a **valid multi-page PDF whose every
page says only 보안메일 비밀번호 인증창.** It has real byte size and a real page
count, so existence/size checks pass.

Before naming any headless-rendered Hometax output `_전자세금계산서.pdf`, open
it and assert the text contains an amount and a supplier. If the extracted text
is the PIN prompt, you have a **PIN gate, not an invoice** — discard the PDF,
keep the original HTML, and report the tax invoice as not retrieved.

The same false-success shape applies to a screenshot: a render of the encrypted
shell is not a render of the document. Decryption requires the real browser
flow in the SKILL.md Hometax section.

## Absence is a reportable state, and it has causes worth naming

Not every unmatched statement is a tooling failure. Before reporting "not
found", check for a still-open payment request to that supplier — an invoice
that has not been issued yet is a legitimate answer. Recurring utility/gas
statements (many delivery dates in one file) are the usual case for this.

**Split the cause by whether a 결제요청 thread exists at all.** These are three
different statuses and reporting them as one "not found" hides the actionable
one:

| 결제요청 thread | Vendor's reply | Status |
|---|---|---|
| exists | has the quote/invoice attached | retrieved — download it |
| exists, no reply yet | — | **awaiting the vendor** — invoice legitimately not issued |
| none exists | — | **never requested** — the draft was never sent |

The third row is the only one where the next action is to create and send the
payment-request draft. A file can also share a supplier with an already-issued
statement and still lack its own quote — vendor bundles several statements into
one reply, so match on **amount and item**, not on supplier and thread alone.

## Headless print-to-PDF of the Hometax HTML proves nothing

`msedge --headless --print-to-pdf` (or the same via `Page.printToPDF`) on an
undecrypted `NTS_eTaxInvoice.html` returns a **valid multi-page PDF whose every
page says only 보안메일 비밀번호 인증창.** It has real byte size and a real page
count, so existence/size checks pass.

Before naming any headless-rendered Hometax output `_전자세금계산서.pdf`, open
it and assert the text contains an amount and a supplier. If the extracted text
is the PIN prompt, you have a **PIN gate, not an invoice** — discard the PDF,
keep the original HTML, and report the tax invoice as not retrieved.

The same false-success shape applies to a screenshot: a render of the encrypted
shell is not a render of the document. Decryption requires the real browser
flow in the SKILL.md Hometax section.

## Disambiguation keys, in order

1. Supplier name in the Hometax subject must equal the supplier you OCR'd from
   the statement. One statement → one supplier; never let a same-week mail from
   a different supplier win.
2. Item list from the statement must appear in the **vendor's** email in the
   same thread as the 결제 요청. That thread is the real join key; Hometax
   cannot confirm items.
3. Issue date should be on or after the receipt date, and the vendor's reply
   ("세금계산서 발행하였고, 견적서 송부드립니다") should exist near it.
4. Total amount, when both sides show it, is the final check.

## Absence is a reportable state, and it has causes worth naming

Not every unmatched statement is a tooling failure. Before reporting "not
found", check for a still-open payment request to that supplier — an invoice
that has not been issued yet is a legitimate answer. Recurring utility/gas
statements (many delivery dates in one file) are the usual case for this.

## Bootstrapping the Paperworks helpers

`C:\Users\user\paperworks\tools\` has no `__init__.py`, and its modules import
each other by absolute name. To load them:

```python
import sys, types, importlib.util
BASE  = r"C:\Users\user\paperworks"
TOOLS = BASE + r"\tools"
sys.path.insert(0, BASE)

import config as cfgmod
cfgmod.cfg.GOOGLE_TOKEN_FILE       = r"C:\Users\user\.gmail-mcp\token.json"
cfgmod.cfg.GOOGLE_CREDENTIALS_FILE = r"C:\Users\user\.gmail-mcp\credentials.json"

pkg = types.ModuleType("tools"); pkg.__path__ = [TOOLS]; sys.modules["tools"] = pkg
spec = importlib.util.spec_from_file_location("tools.gmail_tool", TOOLS + r"\gmail_tool.py")
gt = importlib.util.module_from_spec(spec); sys.modules["tools.gmail_tool"] = gt
spec.loader.exec_module(gt); pkg.gmail_tool = gt
```

Then patch the service factory on every module that imported it, since each one
binds the symbol at import time:

```python
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

def _svc():
    creds = Credentials.from_authorized_user_file(cfgmod.cfg.GOOGLE_TOKEN_FILE)
    if not creds.valid:
        creds.refresh(Request())
        open(cfgmod.cfg.GOOGLE_TOKEN_FILE, "w", encoding="utf-8").write(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

gt._get_service = _svc
```

Pass no `scopes` to `from_authorized_user_file`. The helper modules request
`gmail.send` / `gmail.modify` / `drive`, which the token was not granted;
supplying them makes `refresh()` raise `invalid_scope` even for read-only work.

## Scanned statements

Transaction statements are image-only; PyMuPDF returns 0 characters. Rasterize
page 1 at ~250 dpi and OCR — the supplier block and item rows are both on
page 1, and a handful of pages is enough to name the supplier. OCR all pages
when the item list itself is needed.

For the supplier block specifically, crop the top ~32% of page 1 at ~400 dpi and
use `--psm 4` or `--psm 11`. `--psm 6` assumes a uniform column structure and
mangles these table layouts badly enough to lose 상호/사업자등록번호/이메일
entirely, which then poisons every downstream match. Use psm 6 only for the item
table.

Read every page before fixing on a single date/amount: a two-page statement can
hold two separate transactions (different receipt dates, different totals).
Verify the extracted amount against the sum of the OCR'd item rows rather than
trusting a single `합계금액` token.
