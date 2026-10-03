# bioRxiv API — 실시간 검증 결과

## 검증일: 2026-08-19

## API 엔드포인트

- **URL**: `https://api.biorxiv.org/details/biorxiv/{start_date}/{end_date}/{cursor}/{limit}`
- **응답 구조**: `{"messages": [...], "collection": [...]}`

## 키워드 검색 API 없음 — 클라이언트 측 필터링 필요

bioRxiv은 키워드 검색을 지원하지 않습니다. 날짜 범위 내 모든 논문을 가져온 후
초록/제목에서 검색어가 포함되는지 **OR 매칭**으로 필터링해야 합니다.

```python
# 1. 날짜 범위로 bulk fetch
url = f"https://api.biorxiv.org/details/biorxiv/{start_date}/{today}/{cursor}/{limit}"
data = requests.get(url).json()

# 2. OR 매칭 (검색어 중 하나라도 포함되면 통과)
query_terms = [t for t in re.split(r"\s+", query.lower()) if t]
for paper in data["collection"]:
    combined = (paper["title"] + " " + paper.get("abstract", "")).lower()
    if any(term in combined for term in query_terms if term):
        results.append(paper)
```

## 응답 필드

| 필드 | 설명 | 비고 |
|------|------|------|
| `title` | 논문 제목 | |
| `abstract` | 초록 | 없을 수 있음 → `or ""` |
| `authors` | 세미콜론(`;`) 구분 문자열 | `split(";")` 필요 |
| `doi` | DOI | |
| `date` | 날짜 (YYYY-MM-DD) | |
| `id` | bioRxiv ID | URL 구성용 |
| `url` | 논문 URL | 없을 경우 직접 구성 |

## 주의사항

1. **lookback_days=7 권장**: 최근 1-3일간 "Cancer immunotherapy" 키워드가 직접 매칭되지 않는 경우가 많음.
2. **페이지네이션**: `cursor` 위치와 `limit`으로 반복 호출. `collection` 길이가 `limit`보다 짧으면 종료.
3. **404 응답**: 지정한 날짜 범위에 데이터가 없을 경우 404 반환.

## API 제한

- **무료** — 하지만 서버 부하를 줄이기 위해 페이지네이션과 검색어 필터링을 효율적으로 구현해야 합니다.
