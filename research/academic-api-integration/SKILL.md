---
name: academic-api-integration
description: "Springer/Elsevier API를 검증된 엔드포인트·인증·파싱 패턴으로 호출할 때 쓴다."
version: "1.0.0"
author: Hermes Agent
license: MIT
category: research
tags: [Springer, Elsevier, API, Paper Search, requests, Pitfalls]
platforms: [linux, macos, windows]
---

# Academic API Integration — Springer / Elsevier 검증 패턴

**Trigger:** Springer Nature Open Access API 또는 Elsevier ScienceDirect Metadata API를 파이썬 `requests`로 직접 호출할 때, 엔드포인트·인증·쿼리 형식·응답 파싱을 실제 동작하는 형태로 맞춰야 할 때.

**Core:** 두 API 모두 (1) 문서 예제와 실제 동작 엔드포인트가 다를 수 있고, (2) 인증 방식(헤더 vs 쿼리 파라미터)이 다르며, (3) 응답 필드 구조가 직관적이지 않으므로 실제 응답을 보고 파싱을 맞춰야 한다.

---

## 1. Springer Nature Open Access API

### 1.1 실제 동작하는 호출 형태

```
GET https://api.springernature.com/openaccess/json
  ?api_key=<SPRINGER_API_KEY>
  &q=keyword:<검색어>
  &s=1
  &p=<max_results>
Headers: Accept: application/json
```

- **엔드포인트:** `/openaccess/json` (구 `/openaccess/search` 아님)
- **인증:** `api_key`를 **쿼리 파라미터**로 전달. `Ocp-Apim-Subscription-Key` 헤더는 사용 불가(401).
- **쿼리:** `q=keyword:<term>` 형식. `keyword:` 접두사 필수.
- **응답:** JSON. `records[]` 포함.

### 1.2 응답 필드 구조 (실제 관측 기준)

```json
{
  "records": [
    {
      "doi": "10.1186/s44477-026-00045-w",
      "title": "논문 제목",
      "publicationDate": "2026-08-14",
      "url": [
        {"format": "", "platform": "", "value": "http://dx.doi.org/10.1186/..."}
      ],
      "creators": [
        {"creator": "Pennington, Helen E."},
        {"ORCID": "...", "creator": "Labadorf, Adam"}
      ],
      "abstract": {
        "h1": "Abstract",
        "p": ["Background", "Chronic traumatic encephalopathy...", "Methods", "..."]
      }
    }
  ]
}
```

### 1.3 파싱 패턴

```python
# DOI/식별자
paper_id = entry.get("doi") or entry.get("identifier") or ""

# URL: list of dict → 첫 value 추출, 없으면 DOI 링크 fallback
raw_url = entry.get("url", "")
url = ""
if isinstance(raw_url, list):
    for u in raw_url:
        if isinstance(u, dict) and u.get("value"):
            url = u["value"]
            break
elif isinstance(raw_url, dict):
    url = raw_url.get("value") or raw_url.get("url", "")
if not url and paper_id:
    url = f"https://doi.org/{paper_id}"

# 초록: dict → "p" 배열 공백 결합
abstract_raw = entry.get("abstract")
abstract = ""
if isinstance(abstract_raw, dict) and abstract_raw.get("p"):
    abstract = " ".join(abstract_raw["p"]).strip()
elif isinstance(abstract_raw, str):
    abstract = abstract_raw.strip()
if not abstract:
    abstract = ""

# 저자: creators list → 각 항목의 "creator" 값
authors = []
for a in entry.get("creators", []):
    if isinstance(a, dict):
        name = a.get("creator") or a.get("name", "")
        if name:
            authors.append(name)

# 발행일
pub_date = entry.get("publicationDate") or entry.get("datePublished") or ""
```

### 1.4 쿼리 내 `&` 처리

`RESEARCH_TOPIC`에 `autism&macrophage` 같은 복합 키워드가 들어가면, `requests`가 쿼리를 URL 인코딩할 때 `&`가 파라미터 구분자로 오인되어 404가 발생한다.

```python
# search_springer() 내부에서 쿼리 정제
clean_query = query.replace("&", " ").strip()
params = {"q": f"keyword: {clean_query}", ...}
```

### 1.5 제한 및 에러 처리

- **Daily Quota:** 500 Hits/Day
- **Throttling:** 100 Hits/Min → 429 시 `Retry-After` 기반 재시도 (최대 3회, 점진적 백오프)
- **403:** API key 무효 또는 할당량 초과 → 스킵
- **500:** 서버 에러 → 재시도
- API key가 없으면 자동 스킵 (warning 로그)

---

## 2. Elsevier ScienceDirect Metadata API

### 2.1 실제 동작하는 호출 형태

```
GET https://api.elsevier.com/content/metadata/article
  ?query=<검색어>
  &apiKey=<ELSEVIER_API_KEY>
  &view=COMPLETE
  &httpAccept=application/json
Headers: Accept: application/json
```

- **엔드포인트:** `/content/metadata/article`
- **인증:** `apiKey`를 **쿼리 파라미터**로 전달.
- **주의:** `/search/sciencedirect` 또는 `/content/search`는 예시 키로도 404(`RESOURCE_NOT_FOUND`)가 발생한다. 실제 동작 엔드포인트는 `/content/metadata/article`.
- **응답:** `search-results.entry[]` (Dublin Core + prism 메타). 빈 결과 시 `{"@_fa": "true", "error": "Result set was empty"}`.

### 2.2 응답 필드 구조 (실제 관측 기준)

```json
{
  "search-results": {
    "opensearch:totalResults": "0",
    "entry": [
      {
        "@_fa": "true",
        "error": "Result set was empty"
      }
    ]
  }
}
```

유효한 결과가 있을 경우 entry 예시:

```json
{
  "dc:title": "논문 제목",
  "prism:doi": "10.1016/...",
  "prism:publishedDate": "2026-01-15",
  "link": [
    {"@URL": "https://doi.org/10.1016/...", "@ref": "doi"}
  ],
  "author": [
    {"$": "Smith, J."},
    {"author-name": "Kim, S."}
  ]
}
```

### 2.3 파싱 패턴

```python
# 에러 엔트리 필터
entries = data.get("search-results", {}).get("entry", [])
for entry in entries:
    if isinstance(entry, dict) and entry.get("@_fa") == "true":
        continue  # 빈 결과
    if not isinstance(entry, dict):
        continue

    paper_id = (
        entry.get("prism:doi") or entry.get("doi") or
        entry.get("dc:identifier") or entry.get("eid") or ""
    )
    title = entry.get("dc:title") or entry.get("title") or ""

    # URL
    url = ""
    for ln in entry.get("link", []):
        if isinstance(ln, dict):
            v = ln.get("@URL") or ln.get("href") or ln.get("ref", "")
            if v:
                url = v
                break
    if not url:
        url = entry.get("prism:url") or entry.get("URL", "")
    if not url and paper_id:
        if paper_id.startswith("10."):
            url = f"https://doi.org/{paper_id}"
        else:
            url = f"https://www.sciencedirect.com/science/article/pii/{paper_id}"

    # 초록
    abstract = (
        entry.get("dc:description") or entry.get("dc:abstract") or
        entry.get("description") or entry.get("abstract") or ""
    )

    # 저자
    authors = []
    for a in entry.get("author", []):
        if isinstance(a, dict):
            name = a.get("$", a.get("author-name", ""))
            if name:
                authors.append(name)

    # 발행일
    pub_date = (
        entry.get("prism:publishedDate") or entry.get("prism:coverDate") or
        entry.get("dc:date") or ""
    )
```

### 2.4 제한 및 에러 처리

- **Throttling:** 100 Hits/Min → 429 시 `Retry-After` 기반 재시도
- **401:** API key 무효 또는 접근 권한 없음 → 스킵
- **404:** `/search/sciencedirect` 등 잘못된 엔드포인트 → 올바른 엔드포인트 사용
- API key가 없으면 자동 스킵
- 검색 결과가 0건이어도 에러 없이 빈 리스트 반환됨 (`@_fa: true` 엔트리 필터링)

---

## 3. 공통 패턴

### 3.1 재시도 로직

```python
max_retries = 3
for attempt in range(max_retries):
    r = requests.get(url, params=params, headers=headers, timeout=60)
    if r.status_code == 429:
        retry_after = int(r.headers.get("Retry-After", "60"))
        time.sleep(retry_after)
        continue
    if r.status_code == 401:
        logger.warning("API key 오류")
        return []
    if r.status_code >= 500:
        time.sleep(2 + attempt * 3)
        continue
    r.raise_for_status()
    data = r.json()
    break
else:
    logger.error("모든 재시도 실패")
    return []
```

### 3.2 API key 로딩

```python
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("SPRINGER_API_KEY") or os.getenv("ELSEVIER_API_KEY")
if not api_key:
    logger.warning("API key 없음 - 스킵")
    return []
```

---

## 4. 관련 파일

- `references/springer-oa-api.md` — Springer Open Access API 상세 스펙 및 실제 응답 예제
- `references/springer-oa-verification.md` — 실제 동작하는 curl/Python 레시피, 쿼리 인코딩 검증(`+`/`%20`/`&`/`'`), 이번 세션 검증 결과
- `references/elsevier-metadata-api.md` — Elsevier Metadata API 상세 스펙 및 실제 응답 예제
- `references/elsevier-metadata-verification.md` — 실제 동작하는 curl/Python 레시피, 404였던 과거 엔드포인트, 이번 세션 검증 결과

---

## 5. 관련 스킬

- `research_new` — 이 스킬의 패턴을 실제 파이프라인(`paper_search.py`)에 적용한 스킬
