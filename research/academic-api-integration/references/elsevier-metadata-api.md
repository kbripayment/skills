# Elsevier ScienceDirect Metadata API — 검증 스펙

## 엔드포인트

```
GET https://api.elsevier.com/content/metadata/article
```

**잘못된 엔드포인트 (404 발생, 예시 키로도 재현됨):**
- `/search/sciencedirect` (GET 또는 POST) → 404 `RESOURCE_NOT_FOUND`
- `/content/search` → 404

## 인증

- `apiKey`를 **쿼리 파라미터**로 전달.
- `Accept: application/json` 헤더.
- `view=COMPLETE` 파라미터 포함 (전체 메타데이터).

## 쿼리 파라미터

| 파라미터 | 설명 | 예시 |
|----------|------|------|
| `query` | 검색어 | `?query=tauopathy` |
| `apiKey` | API 키 | `&apiKey=your_elsevier_api_key_here` |
| `view` | 메타데이터 레벨 | `&view=COMPLETE` |
| `httpAccept` | 응답 포맷 | `&httpAccept=application/json` |

또는 DOI로 직접 조회:
```
?doi=10.1016/j.cell.2015.05.005&apiKey=<키>&view=COMPLETE&httpAccept=application/json
```

## 실제 응답 예시 (tauopathy 검색 — 빈 결과)

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

## 유효한 result가 있을 때의 entry 구조

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
  ]
}
```

## 제한

- **Throttling:** 100 Hits/Min
- 429 시 `Retry-After` 헤더 기반 재시도
- API key가 없거나 무효하면 스킵
- 검색 결과가 0건이어도 에러 없이 빈 리스트 반환됨

## 참고 문서

- 공식: https://api.elsevier.com/documentation/ScienceDirect_Metadata_API.pdf
