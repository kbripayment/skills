# Groq Vision LLM normaliser — prompt and response shape

This is the prompt and JSON shape used by `normalize_with_groq()`
in the `hermes_gmail_excel.py` automation. Copy it verbatim when
building another Vision-LLM post-processor.

## System / user prompt

```text
You are an OCR post-processor for laboratory inspection photos.
Given the raw OCR text below plus the original image, normalise the text into
a clean JSON object describing the items detected.

Rules:
- Identify each distinct product line: brand (if any), catalog number,
  size (e.g. "100 ug", "500 g"), quantity (number) and unit (e.g. "ea").
- Output ONLY the JSON, no surrounding prose, no markdown fences.
JSON shape:
{
  "items": [
    {"brand": "Example Chemicals", "catalog": "A9647-500G",
     "name": "Example Chemicals A9647-500G", "size": "500 g",
     "quantity": 4, "unit": "ea", "raw_line": "Example Chemicals A9647-500G 4ea"}
  ],
  "note": "optional short explanation"
}
- If the OCR text is too noisy or unrelated to a product list, return {"items": []}.
- Do not invent products that are not visible in the image or text.
```

The user message includes the OCR text wrapped in a triple-backtick
block plus the original image (as `image_url` with a base64 data
URL).

## Request payload

```python
payload = {
    "model": "llama-3.2-11b-vision-preview",   # or 90b
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": f"OCR text:\n```\n{ocr_text}\n```\n\nNormalise into JSON."},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    }],
    "temperature": 0.0,
    "max_tokens": 1024,
}
```

**Do NOT** include `response_format={"type": "json_object"}` — Groq
vision models reject that field with 400.

## Response handling

```python
content = resp.json()["choices"][0]["message"]["content"]
data = _extract_json(content)  # tolerant: strips ```json fences, finds {...}
items = data.get("items") if isinstance(data, dict) else None
```

`items` is a list of dicts. Normalise each entry to:

```python
{
    "brand":   "Example Chemicals",
    "catalog": "A9647-500G",
    "name":    "Example Chemicals A9647-500G",
    "size":    "500 g",
    "quantity": 4,            # int
    "unit":    "ea",
    "raw_line": "Example Chemicals A9647-500G 4ea",
    "source":  "groq_vision",
}
```

If `name` is empty but `brand`/`catalog` are present, compose
`name = " ".join([brand, catalog, size])`.

## Known failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `400 Bad Request` | model is not image-capable (e.g. `qwen/qwen3.6-27b`) | switch to `llama-3.2-*-vision-*` |
| `400 Bad Request` with `response_format` | not supported on vision | remove the field, parse JSON defensively |
| `429 Too Many Requests` | free tier ~30 req/min | exponential backoff (max 8s), spread calls |
| Empty `items` | LLM detected no product lines | trust the LLM, fall through to original OCR result |

## When to invoke

Always invoke Groq Vision only after Tesseract + PaddleOCR have
already been tried. The noisy heuristic:

```python
noisy = (
    len(cleaned_text) < 200
    or len(products) == 0
    or all(not p.get("catalog") for p in products)
    or any("Aodnich" in (p.get("brand") or "") for p in products)
)
```

The last clause catches `Example Chemicals` → `Sigma-Aodnich` OCR
mistakes (a recurring failure mode in this user's lab photos).
