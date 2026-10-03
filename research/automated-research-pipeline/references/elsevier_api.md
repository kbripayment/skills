# Elsevier API (Scopus / ScienceDirect) — 실시간 검증 결과

## 검증일: 2026-08-19

## API 엔드포인트

- **URL**: `https://api.elsevier.com/content/search`
- **GitHub 래퍼**: https://github.com/ElsevierDev/elsapy (2025년 1월 **Archived**)

## 인증 방식

- 헤더: `X-ELS-APIKey: <api_key>`
- 환경 변수: `ELSEVIER_API_KEY`

## Rate Limit

| 제한 종류 | 값 | 비고 |
|----------|-----|------|
| **Throttling** | 100 Hits/Min | 분당 최대 요청 수 |
| **Daily Quota** | 없음 (API key별 다름) | 서비스 계약에 따라 제한 |

## 응답 구조

```json
{
  "search-results": {
    "entry": [
      {
        "dc:identifier": "SCOPUS_ID:12345",
        "prism:doi": "10.1016/j.cell.2024.01.001",
        "dc:title": "논문 제목",
        "prism:url": "https://api.elsevier.com/...",
        "dc:description": "초록 내용",
        "dc:date": "2024-01-01",
        "creators": [{"name": "Author, A."}],
        "author": [{"$": "Author, A."}]
      }
    ]
  }
}
```

## Rate Limit 대응 패턴

```python
for attempt in range(max_retries):
    r = requests.get(base_url, params=params, headers={
        "Accept": "application/json",
        "X-ELS-APIKey": api_key,
    }, timeout=60)

    if r.status_code == 429:
        retry_after = int(r.headers.get("Retry-After", "60"))
        time.sleep(retry_after)
        continue
    if r.status_code == 401:
        # API key 무효 — 즉시 중단
        return []
    if r.status_code == 500:
        time.sleep(2 + attempt * 3)  # exponential backoff
        continue
    r.raise_for_status()
    break
```

## 주의사항

1. **elsapy 라이브러리는 Archived** — 직접 HTTP 호출 권장 (`requests` + `X-ELS-APIKey` 헤더)
2. **401 응답** = API key 무효 → 즉시 검색 중단
3. **429 응답** = Throttling 제한 → `Retry-After` 헤더 기반 재시도
4. **저자 필드**: `author` 키가 리스트일 수도 딕셔너리일 수도 있음 — `isinstance` 체크 필요
5. **API key가 없으면 스킵** (warning 로그만 출력, 다른 출처 검색은 정상 진행)
6. **초록 필드**: `dc:description` 또는 `dc:abstract`에 위치 (없을 수 있음)

## Related API

- **Scopus Search API**: `https://api.elsevier.com/content/search/scopus` (별도 Scope 필요)
- **ScienceDirect API**: `https://api.elsevier.com/content/search/scienceDirect` (Full text)