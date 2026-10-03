# Script Integration: statement_pdf_inspector.py with --pin-protect

## CLI

```bash
python statement_pdf_inspector.py --folder Y:\\ --pattern "*거래명세서.pdf" --pin-protect
python statement_pdf_inspector.py --folder Y:\\ --pattern "*거래명세서.pdf" --pin-off
```

- `--pin-protect PIN` (기본 `5148280611`): PDF를 PIN 입력 iframe 뷰어 HTML로 감싼다.
- `--pin-off`: 원본 HTML을 그대로 쓴다.

## 심볼

- `PIN_PROTECT_DEFAULT_PIN`, `PIN_PROTECT_HTML_TEMPLATE`
- `_generate_pin_protected_html(html_text, pdf_path, pin) -> str`
- `process_pdf_files(..., pin_protect: Optional[str] = None)`

## 모듈 로드 요약

`statement_pdf_inspector.py`는 `from html_table import render_html_table`을 한다. `html_table.py`는 pip 패키지가 아니라 scripts 폴더의 로컬 모듈이므로, `importlib.util.spec_from_file_location`으로 직접 임포트할 때는 **임포트하는 쪽이 `os.path.dirname(script_path)`를 `sys.path`에 넣거나 모듈을 수동 주입**해야 한다. exe 실행이라 `sys.path`만으로는 모듈이 안 잡힌다.

같은 이유로 `tools.gmail_tool` / `tools.sheets_tool`을 쓸 때도 `paperworks`를 `sys.path`에 넣어야 `from config import cfg`가 성립한다.