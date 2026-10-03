# Dynamic dependency guards & Vision LLM signature auditing

Concrete session transcript and reproduction recipe for two
recurring failure modes in the
`hermes_gmail_excel.py` / Paperworks pipeline.

---

## Symptom 1 — PyPI package name vs importable module name

### What you see in the log

```
INFO Authenticating...
INFO Token refreshed.
INFO Searching Gmail with query: subject:검수사진 newer_than:7d
INFO Found 4 Gmail messages.
INFO Processing message 19fcb652dfe45091
INFO Saved 20260804_140440.jpg to C:\Users\user\Downloads\20260804_140440.jpg
   ╔══════════════════════════════════════════════════════════╗
   ║ ModuleNotFoundError: No module named 'google-api-python-client' ║
   ╚══════════════════════════════════════════════════════════╝

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "...\hermes_gmail_excel.py", line 38, in install_if_missing
    __import__(pkg)
  File "...\hermes_gmail_excel.py", line 42, in install_if_missing
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    ^^^^^^^^^^
NameError: name 'subprocess' is not defined
```

The first crash happens because `__import__("google-api-python-client")`
uses the **PyPI distribution name**, not the **Python module name**.
The venv actually contains `google_api_python_client-2.194.0` (which
exports the `googleapiclient` module). The fallback then tries
`subprocess.check_call(...)` to auto-install — but `subprocess` is not
imported in the module scope (a previous cleanup patch had removed it
in favor of `datetime`), so the fallback itself crashes with NameError.

### Root cause

There is **no `subprocess` import** anywhere in the module after a
prior cleanup patch, and the auto-install path depends on it. In a
managed venv (like `hermes-agent`), blindly spawning `pip install` is
also a footgun — the dependency is supposed to be already present.

### Fix (curator-verified, 2026-08-05)

1. Replace `install_if_missing` so it **raises a clear `ImportError`
   instead of spawning `pip`** in managed environments:

   ```python
   def install_if_missing(pkg: str) -> bool:
       try:
           __import__(pkg)
           return False
       except ImportError:
           raise ImportError(
               f"[install_if_missing] Required package {pkg!r} is not "
               "importable in the current interpreter. The hermes-agent "
               "venv normally provides it; check that you are running "
               "'C:\\Users\\user\\AppData\\Local\\hermes\\hermes-agent"
               "\\venv\\Scripts\\python.exe' and that the dependency "
               "is installed."
           )
   ```

2. Add a `_REQUIRED_MODULES` mapping in the `__main__` block so the
   import check uses the **real module name**:

   ```python
   _REQUIRED_MODULES = {
       "google-api-python-client": "googleapiclient",
       "google-auth": "google.auth",
       "google-auth-oauthlib": "google_auth_oauthlib",
       "Pillow": "PIL",
       "pytesseract": "pytesseract",
       "python-dotenv": "dotenv",
   }
   for _pypi_name, module_name in _REQUIRED_MODULES.items():
       try:
           __import__(module_name)
       except ImportError:
           try:
               install_if_missing(_pypi_name)
           except ImportError:
               pass  # logged above; main() continues best-effort
   ```

### Why this matters

- The managed `hermes-agent` venv bundles every dependency this
  script needs. Blind `pip install` from inside the script will hit
  the venv's allowlist, fail silently, or write outside the user's
  intended environment.
- A clear `ImportError` (with the expected venv path) tells the next
  agent "you're in the wrong interpreter" instead of "I tried to
  install and crashed."

### Known PyPI ↔ module mappings to remember

| PyPI name | Module name |
|-----------|-------------|
| `google-api-python-client` | `googleapiclient` |
| `google-auth` | `google.auth` |
| `google-auth-oauthlib` | `google_auth_oauthlib` |
| `google-auth-httplib2` | `google_auth_httplib2` |
| `python-dotenv` | `dotenv` |
| `Pillow` | `PIL` |
| `PyYAML` | `yaml` |
| `python-dateutil` | `dateutil` |
| `scikit-learn` | `sklearn` |
| `opencv-python` | `cv2` |
| `pytesseract` | `pytesseract` |

---

## Symptom 2 — `filename` not in Vision LLM signature

### What you see in the log (5× per run, once per attachment)

```
INFO Sleeping 12.0s before next Groq call…
WARNING Groq vision call failed (attempt 1): name 'filename' is not defined
WARNING Groq vision: 429 rate-limited; backing off.
WARNING Groq vision: 429 rate-limited; backing off.
ERROR Groq vision normalisation gave up: name 'filename' is not defined
INFO   OCR (paddle) for 20260804_140440.jpg: 'CU'
...
INFO Total processed rows: 0
INFO Groq Vision calls made: 5
filename,supplier_email,item,quantity
(no items found)
```

### Root cause

`normalize_with_groq()` references `filename` inside the retry loop
(in a log line `f"Groq vision raw response for {filename}: ..."`),
but the function signature does not declare it:

```python
def normalize_with_groq(image_bytes: bytes, ocr_text: str,
                         mime: str = "image/jpeg") -> Optional[List[Dict]]:
    ...
    logger.info(f"  Groq vision raw response for {filename}: {content[:400]!r}")
```

The first `requests.post()` call hits the log line, raises `NameError`,
gets caught by `except Exception as e`, and the loop retries with the
same crash — three times. The exception type recorded as `last_err`
is the `NameError`, so the final log says
`gave up: name 'filename' is not defined`.

### Fix (curator-verified, 2026-08-05)

1. Extend the signature with `filename: str = ""` (default keeps
   backward compatibility with any existing direct callers):

   ```python
   def normalize_with_groq(
       image_bytes: bytes,
       ocr_text: str,
       mime: str = "image/jpeg",
       filename: str = "",
   ) -> Optional[List[Dict[str, Any]]]:
       ...
       logger.info(f"  Groq vision raw response for {filename}: {content[:400]!r}")
   ```

2. Pass it from the caller:

   ```python
   groq_call_count += 1
   groq_items = normalize_with_groq(
       image_bytes, cleaned_text, mime_type or "image/jpeg",
       filename=filename,
   )
   ```

### Audit checklist for vision / OCR helpers

Whenever you add or modify a Vision LLM helper, scan for these
identifiers in **both** the signature **and** the body:

- `filename` — image identity for logs
- `mime` / `mime_type` — payload construction
- `image_bytes` — base64 source
- `prompt` / `system_prompt` — used in the payload

If any of them appears in the body but not in the signature, the
helper will crash at first call, not at definition time. Add it as a
keyword argument with a default value to keep tests / mocks working.

### What the final working output looks like

```
INFO Groq vision raw response for 20260803_132600.jpg: '\n<think>The user wants to extract product information...'
INFO Groq vision normalised 20260803_132600.jpg → 1 item(s).
INFO OCR (paddle) for 20260803_132600.jpg: 'biorbyt\nExplore Bioreagents\nProduct\nD\nRecombinant\nHuman\n(orb315\nSize\n100 μg\nCatalog Number\norb3153859\n...'
INFO Total processed rows: 1
INFO Groq Vision calls made: 5
filename,supplier_email,item,quantity
20260803_132600.jpg,"김철수(공용)lab" <account@example.com>,Recombinant Human DiP2A Protein,1
```

`Total processed rows` jumps from `0` to `1`, the OCR row gets a
structured `item` column, and the Groq vision log line now references
a real filename.

---

## Cross-references

- **Skill body** — see the three pitfalls in `SKILL.md`
  (PyPI/module mapping, Vision signature, Sheet `invalid_scope`).
- **`references/groq-vision-normalisation.md`** — full prompt +
  response shape for `normalize_with_groq`.
- **`references/paperworks-import-recipe.md`** — copy-paste helper
  for loading Paperworks tools when there is no `__init__.py`.
- **`scripts/check_ocr_dependencies.py`** — verify interpreter path,
  Tesseract binary, PaddleOCR import, and Groq API key reachability
  before a run.
