# Springer Nature Open Access API — 이번 세션 검증 레시피 (2026-08-21)

## 검증이 필요한 상황
- API 키 유효성을 확인할 때.
- 엔드포인트·인증 방식이 문서 예제와 다른지 확인할 때.
- 쿼리 인코딩(공백, `&`, `'` 등)이 응답을 망가뜨리는지 확인할 때.

## 실제 동작하는 curl 호출 (키 값은 [REDACTED])

### Springer /openaccess/json + api_key 쿼리 파라미터
```bash
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.springernature.com/openaccess/json?api_key=<SPRINGER_API_KEY>&q=keyword%3A%20tauopathy&s=1&p=2" \
  -H "Accept: application/json"
```
- 응답: 200 OK, `{"records":[...]}` + `result[0].total`.
- 이번 세션 실제 결과 (tauopathy, p=2): `total: "323"`, records 2건 파싱 성공.

### 공백 인코딩 방식 비교 (둘 다 허용)
```bash
# test1: + 공백
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.springernature.com/openaccess/json?api_key=<KEY>&q=keyword%3A+maternal+immune+activatio+n&s=1&p=2" \
  -H "Accept: application/json"

# test2: %20 공백
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.springernature.com/openaccess/json?api_key=<KEY>&q=keyword%3A%20maternal%20immune%20activation&s=1&p=2" \
  -H "Accept: application/json"
```
- 둘 다 200 OK.

### `&` 포함 키워드는 404 유발 → 치환 필요
```bash
# 치환 전 (autism&macrophage → 404)
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.springernature.com/openaccess/json?api_key=<KEY>&q=keyword%3A%20autism%26macrophage&s=1&p=2" \
  -H "Accept: application/json"
# → 404

# 치환 후 (autism macrophage → 200 OK, 25건)
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.springernature.com/openaccess/json?api_key=<KEY>&q=keyword%3A%20autism%20macrophage&s=1&p=2" \
  -H "Accept: application/json"
```
- 코드에서 `query.replace("&", " ").strip()` 적용.

### `'` 포함 키워드 (alzheimer's disease)
```bash
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.springernature.com/openaccess/json?api_key=<KEY>&q=keyword%3A%20alzheimer%27s%20disease&s=1&p=2" \
  -H "Accept: application/json"
```
- 200 OK, 2건 반환. 아포스트로피 자체(%27)는 API가 처리 가능하지만, 코드 레벨에서는 안정성을 위해 `'` 제거(`alzheimers disease`) 처리 적용.

## Python requests 검증 (이번 세션에서 curl 환경 이슈로 사용)
```python
import requests
r = requests.get(
    "https://api.springernature.com/openaccess/json",
    params={
        "api_key": "<SPRINGER_API_KEY>",
        "q": "keyword: tauopathy",
        "s": 1,
        "p": 2,
    },
    headers={"Accept": "application/json"},
    timeout=60,
)
print(r.status_code)
print(r.json().get("records", [])[:2])
```
- `requests`는 쿼리 파라미터를 자동 URL 인코딩하므로, `&` 처리만 코드에 수동으로 넣어주면 됨.

## 파싱 시 확인할 실제 필드 (이번 세션 실제 응답 기준)
- `records[].doi` 또는 `records[].identifier` → 논문 ID.
- `records[].url` → `[{"format":"", "platform":"", "value":"https://doi.org/..."}]` 구조. 첫 요소의 `value` 사용.
- `records[].creators` → `[{"creator":"Name", ...}, {"ORCID":"...","creator":"Name2"}]`. 각 항목의 `creator` 키 값 추출.
- `records[].publicationDate` → `"2026-08-14"` 형식.
- `records[].abstract` → `{"h1":"Abstract", "p":["Background", "...", "Methods", "..."]}` 또는 문자열. `p`가 배열이면 공백으로 결합.

## 이번 세션에서 확인한 한계/주의
- curl 호출 환경에서 `exit 49` (python 인터프리터 이슈) 발생 → curl 대신 Python `requests`로 검증.
- 키워드 내 `&`는 반드시 치환. 치환하지 않으면 404.
- `'` 포함 키워드는 API가 받긴 하지만, 사용자 키/쿼리 조합에 따라 404 가능성 → 코드에서 `'` 제거 권장.
