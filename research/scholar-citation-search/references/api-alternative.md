# 대안 API 방식 (선택)

브라우저 방식 대신 API로 Google Scholar 인용 논문을 검색할 수 있는 서비스들.

## SerpApi

- URL: https://serpapi.com/google-scholar-api
- `cites` 파라미터: 대상 논문의 `cited_by` ID로 인용 논문 검색
- 예시: `https://serpapi.com/search?q=arXiv+paper&cites=1234567890`
- 무료 티어: 월 100회 검색. 유료 플랜 있음.
- API 키 필요: `api_key` 파라미터 또는 헤더.

## Serply.io

- URL: https://serply.io/google-scholar-api
- Google Scholar 검색 및 논문 메타데이터 제공.
- API 키 필요. 무료 티어 있음.

## OpenCitations (COCI)

- URL: https://opencitations.net
- COCI(Crossref Open Citation Index): 오픈 인용 데이터.
- Google Scholar보다 범위가 좁지만 무료, 대량 쿼리에 적합.
- API: https://opencitations.net/index/api
- HTTP GET으로 DOI 기반 인용 관계 조회 가능.

## 브라우저 방식과 API 방식의 비교

| 항목 | 브라우저 | API |
|---|---|---|
| 비용 | 무료 | 유료 티어 필요 (대부분) |
| 안정성 | 캡차/차단 가능 | 안정적 (공식 API) |
| 범위 | Google Scholar 전체 | 서비스별 상이 |
| 속도 | 느림 (렌더링 필요) | 빠름 |
| 설정 | 브라우저 도구만 필요 | API 키 등록 필요 |

API 키가 준비되면 이 스킬의 1~3단계를 API 호출로 대체할 수 있다.
