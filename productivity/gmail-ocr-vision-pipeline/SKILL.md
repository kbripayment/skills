---
name: gmail-ocr-vision-pipeline
category: productivity
title: Gmail image attachments → OCR fallback chain → Vision LLM → Sheets cross-check
description: "Tesseract + PaddleOCR + Groq Vision pipeline patterns."
---

# Gmail → OCR → Vision LLM → Sheets pipeline patterns

A class-level skill that captures the *patterns* behind the
`hermes_gmail_excel.py` automation. Use it when designing or
debugging any pipeline that:

1. Pulls image attachments from Gmail.
2. Runs OCR on them with one or more engines.
3. Optionally escalates to a Vision LLM when OCR is noisy.
4. Cross-references the structured output against a Google
   spreadsheet to find rows that still need action.

## OCR fallback chain

Always run engines in **cheap → expensive** order:

```
Tesseract (kor+eng)         ← sub-second per image
   ↓ if text < 4 chars
PaddleOCR (korean model)    ← ~6s per image, better Korean
   ↓ if "noisy" (see below)
Groq Vision LLM             ← ~3-10s per image, best semantics
```

### "Noisy" detection (when to escalate)

Escalate to Groq Vision LLM when ANY of:

- OCR text < 200 characters.
- `build_product_rows` produced 0 products.
- All products have empty `catalog`.
- A product's brand looks OCR-corrupted (heuristic: contains known
  OCR-mistake patterns, e.g. `Sigma-Aodnich` instead of
  `Example Chemicals`).

Do NOT escalate on every image — the Groq free tier returns
`429 Too Many Requests` after roughly 30 requests/minute.

## Common pitfalls (verified in production runs)

### Pitfall 1: PyPI name vs module name in `install_if_missing`

`__import__("google-api-python-client")` raises `ModuleNotFoundError`
because the importable module is `googleapiclient`. Same trap for
`Pillow` → `PIL`, `python-dotenv` → `dotenv`,
`PyYAML` → `yaml`. Two failure modes show up in logs:

1. `ModuleNotFoundError: No module named 'google-api-python-client'`
   when the venv actually has `google_api_python_client` installed.
2. The fallback path then tries `subprocess.check_call([..., "pip",
   "install", pkg])` — which either fails (`NameError: name
   'subprocess' is not defined` if someone removed the import during
   cleanup) or is blocked by the managed-venv policy.

**Fix pattern** — maintain a name→module mapping and use it both for
the import check AND for the install fallback:

```python
_REQUIRED_MODULES = {
    "google-api-python-client": "googleapiclient",
    "google-auth": "google.auth",
    "google-auth-oauthlib": "google_auth_oauthlib",
    "Pillow": "PIL",
    "pytesseract": "pytesseract",
    "python-dotenv": "dotenv",
}

for pypi_name, module_name in _REQUIRED_MODULES.items():
    try:
        __import__(module_name)
    except ImportError:
        # Either call install_if_missing(pypi_name) or raise a clear error
        # instructing the user to use the configured venv.
        raise ImportError(
            f"Required {module_name!r} (PyPI: {pypi_name!r}) missing. "
            "Run inside the pre-configured hermes-agent venv."
        )
```

In managed environments, **prefer raising** over auto-installing. The
hermes-agent venv already bundles every Google/OCR dependency, so
auto-`pip install` is a footgun that hides real config drift.

### Pitfall 2: `filename` not in Vision LLM signature

Symptom in logs (5× per run, one per attachment):

```
WARNING Groq vision call failed (attempt 1): name 'filename' is not defined
ERROR Groq vision normalisation gave up: name 'filename' is not defined
INFO Total processed rows: 0
INFO Groq Vision calls made: 5
```

Cause: `normalize_with_groq(image_bytes, ocr_text, mime)` references
`filename` in a log line (e.g. `f"Groq vision raw response for
{filename}"`) but never accepts it as a parameter. Result: every call
fails inside the retry loop with the same NameError, and `groq_items`
is always `None` — so `build_product_rows` is never enriched and the
final CSV/markdown is empty.

**Fix** — extend the signature and the call site:

```python
def normalize_with_groq(
    image_bytes: bytes,
    ocr_text: str,
    mime: str = "image/jpeg",
    filename: str = "",          # ← add
) -> Optional[List[Dict[str, Any]]]:
    ...
    logger.info(f"  Groq vision raw response for {filename}: ...")
    ...

# Caller:
groq_items = normalize_with_groq(
    image_bytes, cleaned_text, mime_type or "image/jpeg",
    filename=filename,          # ← pass it
)
```

Whenever a vision helper logs the image identity (filename, hash,
size), make sure that variable is in scope — pass it explicitly
rather than relying on closure capture from the caller.

### Pitfall 3: Sheet `invalid_scope` despite token claiming the scope

If `google_token.json` lists `spreadsheets` in its `scopes` field
but the API still returns `invalid_scope: Bad Request`, the most
common cause is **client_id mismatch** — the cached token was issued
under a different OAuth client (e.g. `662388454361-…`) than the
`credentials.json` now being used. The hermes-agent venv's stored
token and the Paperworks `credentials.json` can drift apart.

**Fix** — re-authenticate once with the union of scopes against the
*current* `credentials.json`:

```python
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
# Delete the old token and run an interactive OAuth flow once.
# The script's try/except around `service.spreadsheets().get()` will
# fall back to "미확인" (Unknown) status, which is safe.
```

Until re-auth runs, the safe behavior is to log the scope mismatch
and mark cross-check rows as `미확인` rather than crashing. The
existing fallback in `find_unreceived_sheet_rows` already does this.

## Gmail attachment API gotchas

The Gmail API has two ways to walk attachments:

### WRONG (silent failure):

```python
att = service.users().messages().attachments()        # Resource
att.list(userId="me", messageId=msg["id"]).execute()  # AttributeError
```

`service.users().messages().attachments` is a Resource that
requires explicit `(userId, messageId)` arguments before
`.list()`/`.get()` are valid. Empty `()` returns a Resource whose
`.list()` does not exist.

### RIGHT:

```python
# Option A — get bytes for a known attachmentId:
data = service.users().messages().attachments().get(
    userId="me", messageId=msg["id"], id=att_id,
).execute()
payload = data["data"] + "=" * (-len(data["data"]) % 4)  # pad!
image_bytes = base64.urlsafe_b64decode(payload)

# Option B — walk the payload tree:
def collect(parts):
    out = []
    for p in parts or []:
        if p.get("filename") and p.get("body", {}).get("attachmentId"):
            out.append({"id": p["body"]["attachmentId"],
                        "filename": p["filename"],
                        "mimeType": p.get("mimeType", "")})
        if p.get("parts"):
            out.extend(collect(p["parts"]))
    return out
```

Gmail's base64url omits padding — always add `=*` to round out
to a multiple of 4 before `urlsafe_b64decode`.

## OCR engine specifics

### PaddleOCR 3.x

```python
from paddleocr import PaddleOCR
ocr = PaddleOCR(use_textline_orientation=True, lang="korean")
# `show_log` was removed in 3.x — passing it raises TypeError.
# `use_angle_cls` and `use_textline_orientation` are mutually exclusive.
```

Fallback ladder to handle 2.x / 3.x / future API churn:

```python
try:
    ocr = PaddleOCR(use_textline_orientation=True, lang="korean")
except TypeError:
    try:
        ocr = PaddleOCR(use_textline_orientation=True, lang="korean",
                        show_log=False)
    except TypeError:
        ocr = PaddleOCR(use_angle_cls=True, lang="korean", show_log=False)
```

### Tesseract

`tesseract.exe` is **not** a pip package. On Windows, the default
install path is `C:\Program Files\Tesseract-OCR\tesseract.exe`.
`shutil.which("tesseract")` often misses it because the path has
a space; check known locations explicitly:

```python
def find_tesseract():
    explicit = os.getenv("TESSERACT_CMD")
    if explicit and os.path.exists(explicit):
        return explicit
    import shutil
    found = shutil.which("tesseract")
    if found:
        return found
    for cand in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
    ):
        if os.path.exists(cand):
            return cand
    return None
```

Korean recognition needs `kor.traineddata` — verify with
`tesseract --list-langs`.

## Catalog number regex

Catalog IDs look like `A9647-500G`, `P8340-1KG`, `orb3153859`,
`H6908-100MG`. UniProt IDs look like `Q14689`. Naive regex
(`[A-Z]{1,4}\d{2,5}`) catches UniProt IDs as false positives.

```python
_CATALOG_RE = re.compile(
    r"\b(?:[A-Z]{2,5}\d{3,5}(?:-\d+(?:\.\d+)?[A-Z]+)?"
    r"|(?:[A-Z]{2,5}-)?\d{4,5}-[A-Z]{1,3})\b"
)
# - Requires 2-5 alpha prefix OR 4-5 digit prefix
# - Requires 3+ digits after the alpha prefix (excludes UniProt)
```

## Groq Vision LLM integration

```python
url = "https://api.groq.com/openai/v1/chat/completions"
headers = {"Authorization": f"Bearer {api_key}",
           "Content-Type": "application/json"}

payload = {
    "model": "llama-3.2-11b-vision-preview",   # IMAGE-capable only
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": OCR_TEXT_FOR_CONTEXT},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }],
    "temperature": 0.0,
    "max_tokens": 1024,
}
```

### Gotchas

- **Image-capable models are limited** to `llama-3.2-*-vision-*`
  on Groq. Other configured models (e.g. `qwen/qwen3.6-27b`)
  reject `image_url` payloads with 400.
- **`response_format={"type": "json_object"}`** is NOT supported
  on Groq vision models. Ask for JSON in the prompt and parse
  defensively.
- 429 rate limit on the free tier is roughly 30 req/min.
  Implement exponential backoff (max 8s) before retrying; if the
  burst is large (5+ images), expect several calls to fail.
- 429 회피 패턴 (Groq 채팅 API vision 이미지 요청): Groq Vision API뿐 아니라
  채팅 API(qwen/qwen3.8-27b)로도 image_url 포함한 completion 요청 시 동일하게
  429 발생. 호출 간격 time.sleep(10) 이상 + 3회 재시도(retry on 429)로 회피.
  max_tokens=900 이하 유지.

## Paperworks dynamic import pattern

Paperworks at `C:\Users\user\paperworks` ships `config.py` and
`tools/*.py` but **has no `tools/__init__.py`**, so `import tools.x`
fails. Load them directly:

```python
import importlib.util, sys
sys.path.insert(0, r"C:\Users\user\paperworks")
sys.path.insert(0, r"C:\Users\user\paperworks\tools")

spec = importlib.util.spec_from_file_location(
    "sheets_tool", r"C:\Users\user\paperworks\tools\sheets_tool.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
service = mod._get_service()
```

Also patch `cfg.GOOGLE_TOKEN_FILE` / `cfg.GOOGLE_CREDENTIALS_FILE`
to point at your own token if Paperworks's default location is empty.

## Sheets fuzzy matching

Score each OCR product against every sheet row whose target column
(e.g. `입고일`) is empty:

| Signal | Weight |
|--------|-------:|
| Catalog substring in sheet row | +0.50 |
| Catalog digits (≥4) in sheet row | +0.30 |
| Brand name in sheet row | +0.25 |
| ≥2 OCR tokens overlap sheet tokens | +0.20 |
| 1 OCR token overlap | +0.15 |
| OCR size in sheet row | +0.15 |
| OCR raw line substring of sheet row | +0.10 |

Bands: ≥0.80 strong, 0.55-0.79 weak (flag ⚠), <0.55 ignore.

## OAuth scope expansion

When the same Google account needs both Gmail readonly AND
Sheets access, the cached token must include both scopes.
`OAUTHLIB_RELAX_TOKEN_SCOPE=1` lets
`Credentials.from_authorized_user_file()` load a token whose
scopes are a subset, but the API call itself will still return
`403 insufficient authentication scopes` if the narrower scope is
what's in the file. The fix is to delete the token file and
re-authenticate with the union of scopes:

```python
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
```

## Inspection photos by date (generic item names)

When a transaction statement's only line item is a generic category
(표준가스, 시약, 소모품) instead of a product name, product-token scoring
finds nothing and the search silently returns zero photos. Do not loosen
the scorer — sweep the sender by date window and match the subject
prefix (`N/M 검수사진 송부`) exactly, then filter attachments by content.
See `references/inspection-photo-by-date.md` for the full procedure.

Two rules from that path that generalise to any attachment batch:

- **Downscale every attachment to ≤1200px (q85) before `vision_analyze`.**
  Phone-camera originals at 4128px and larger time out. Bigger montages
  are not the fix — 4-up montages time out where individual 1100px files
  succeed. Batch by making parallel per-file calls.
- **A ±N-day Gmail date window returns neighbouring dates' mail.** Use
  the window to fetch, then select on the exact subject prefix.

## Provider chain이 통째로 죽었을 때

Groq 이미지 쿼터 소진 + NVIDIA 503 + llama.cpp 무응답이 겹치면 어떤
폴백도 살아있지 않다. **스크립트를 재시도하거나 기다리지 말고, 에이전트
자신의 `vision_analyze`로 직접 처리한다** — 이 경로는 스크립트의
provider chain과 무관하게 정상 동작한다. 각 provider를 직접 probe해
판단하고( Groq 채팅 200이어도 Vision 쿼터는 별개다 ), 절차는
`references/statement-pdf-vendor-drafts.md` 참조.

폴백 호출 타임아웃은 티어별로 분리한다(`LLM_TIMEOUT_REMOTE` 150초 /
`LLM_TIMEOUT_ALT` 300초 / `LLM_TIMEOUT_LOCAL` 1800초, 로컬 Vision 900초).
`timeout=1800` 하드코딩은 무응답 티어 하나당 30분을 소모해 배치가
정지한다.

## 버그를 발견했을 때 기록할 곳

발견한 결함은 `automation/scripts/requirement_automation.md` 에 올린다. 그 문서는
**요구사항 문서**이므로 담는 것은 버그 발견 사실 · 원인 · 요구사항 항목 · 회귀 기준뿐이다.

올리지 **않는** 것: 실행 로그 원문, 개별 파일명·시트 행·금액 등 개별 사안 데이터, 수동
처리 내역. 개별 사안을 올리면 다음 작업자가 출처를 추적하지 못하고, 회귀 테스트에
쓰이지 않은 수치가 dead data로 남는다. 요구사항이 아니라면 구현 내역은
`automation/scripts/progress_automation.md` 가 담당한다.

회귀 기준은 개별 사안 설명 대신 코드 블록에 값만 남긴다. 수정자가 그대로 테스트
케이스로 복사할 수 있어야 한다.

**코드 수정이 이미 시작된 절은 건드리지 않는다.** 같은 요구사항을 두 사람이 동시에
고치는 것이 이번 세션에서 실제로 있었고, 그때 먼저 쓴 쪽이 뒤엎였다. 절 상태를
`미구현`/`구현 완료` 로 한 번만 갱신하고 나머지는 두지 않는다.

## See also

- `references/statement-pdf-vendor-drafts.md` — 스캔 거래명세서 → 업체별
  견적서/전자세금계산서 요청 초안, provider chain 교체 → 직접 Vision 전환.
- `references/inspection-photo-by-date.md` — retrieve inspection
  photos for a user-supplied list of statement dates.
- `references/groq-vision-normalisation.md` — full prompt +
  response shape used by `normalize_with_groq()`.
- `references/paperworks-import-recipe.md` — copy-paste helper
  for loading Paperworks tools from a non-package layout.
- `scripts/check_ocr_dependencies.py` — verify Tesseract binary,
  PaddleOCR import, and Groq API key reachability before a run.
