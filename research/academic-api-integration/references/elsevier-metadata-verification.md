# Elsevier ScienceDirect Metadata API — 이번 세션 검증 레시피 (2026-08-21)

## 검증이 필요한 상황
- API 키 유효성을 확인할 때.
- `/content/search` 또는 `/search/sciencedirect`가 404 `RESOURCE_NOT_FOUND`를 반환할 때.
- 검색 결과가 0건일 때 이것이 키/엔티티 문제인지 코드 문제인지 구분할 때.

## 실제 동작하는 curl 호출 (키 값은 [REDACTED])

### Elsevier /content/metadata/article + apiKey 쿼리 파라미터
```bash
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.elsevier.com/content/metadata/article?query=tauopathy&apiKey=<ELSEVIER_API_KEY>&view=COMPLETE&httpAccept=application/json" \
  -H "Accept: application/json"
```
- 응답: 200 OK.
- 이번 세션 실제 결과 (tauopathy): `opensearch:totalResults: "0"`, `entry: [{"@_fa":"true","error":"Result set was empty"}]`.

### 과거에 404였던 엔드포인트 (이제 쓰지 말 것)
```bash
# /content/search → 404 RESOURCE_NOT_FOUND (이번 세션 확인)
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.elsevier.com/content/search?query=tauopathy" \
  -H "X-ELS-APIKey: <ELSEVIER_API_KEY>"

# /search/sciencedirect → 404 (예시 키로도 재현됨)
curl -s -w "\nHTTP:%{http_code}\n" \
  "https://api.elsevier.com/search/sciencedirect?query=tauopathy&apiKey=<ANY_KEY>"
```
- 올바른 엔드포인트는 `/content/metadata/article`.

## 쿼리 인코딩 및 파라미터
- `query`: 검색어 (URL 인코딩 필요, 예: `query=maternal%20immune%20activation`).
- `apiKey`: 쿼리 파라미터로 전달. `X-ELS-APIKey` 헤더는 사용하지 않음.
- `view=COMPLETE`: 전체 메타데이터.
- `httpAccept=application/json`: 응답 JSON 형식.

## Python requests 검증 (이번 세션에서 사용)
```python
import requests
r = requests.get(
    "https://api.elsevier.com/content/metadata/article",
    params={
        "query": "tauopathy",
        "apiKey": "<ELSEVIER_API_KEY>",
        "view": "COMPLETE",
        "httpAccept": "application/json",
    },
    headers={"Accept": "application/json"},
    timeout=60,
)
print(r.status_code)
data = r.json()
entries = data.get("search-results", {}).get("entry", [])
print("entries:", entries)
```
- 200 OK이나 `entry`가 `[{"@_fa":"true","error":"Result set was empty"}]`일 수 있음.
- 이 경우 **키가 무효한 것이 아니라 쿼리 매칭 결과가 없음**. 다른 쿼리/키로 확인 필요.

## 파싱 시 확인할 실제 필드 (이번 세션 실제 응답 구조 기준)

### 에러 엔트리 (빈 결과)
```json
{
  "@_fa": "true",
  "error": "Result set was empty"
}
```
- 파서에서 `@_fa == "true"`인 엔트리는 필터링(스킵).

### 유효 result entry 예시 구조
```json
{
  "dc:title": "논문 제목",
  "prism:doi": "10.1016/...",
  "prism:publishedDate": "2026-01-15",
  "prism:coverDate": "2026-01-15",
  "dc:date": "2026-01-15",
  "link": [
    {"@URL": "https://doi.org/10.1016/...", "@ref": "doi"}
  ],
  "author": [
    {"$": "Smith, J."},
    {"author-name": "Kim, S."}
  ],
  "dc:description": "초록 텍스트",
  "dc:abstract": "초록 텍스트"
}
```

### 파싱 패턴
- 논문 ID: `prism:doi` → `doi` → `dc:identifier` → `eid` 순으로 fallback.
- 제목: `dc:title` → `title`.
- URL: `link[]` 내 `@URL`(또는 `href`) 우선, 없으면 `prism:url`/`URL` → 없으면 DOI면 `https://doi.org/...`, 아니면 `https://www.sciencedirect.com/science/article/pii/...`.
- 초록: `dc:description` → `dc:abstract` → `description` → `abstract` 순.
- 저자: `author[]` 내 `$`(우선) 또는 `author-name`.
- 발행일: `prism:publishedDate` → `prism:coverDate` → `dc:date`.

## 이번 세션에서 확인한 한계/주의
- `tauopathy`, `maternal immune activation` 쿼리는 HTTP 200이지만 0건 반환. 키의 콘텐츠 범위/권한 문제일 가능성 높음(코드 결함 아님).
- Elsevier 0건은 에러 없이 빈 리스트로 돌아오므로, **호출 성공 ≠ 결과 존재**임을 항상 구분.
- 429 시 `Retry-After` 기반 재시도(최대 3회). 401 시 키 무효/권한 없음 → 스킵.
- 잘못된 엔드포인트(`/content/search`, `/search/sciencedirect`)는 예시 키로도 404 → 항상 `/content/metadata/article` 사용.
