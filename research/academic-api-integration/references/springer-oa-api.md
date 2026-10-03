# Springer Nature Open Access API — 검증 스펙

## 엔드포인트

```
GET https://api.springernature.com/openaccess/json
```

**잘못된 엔드포인트 (401 발생):**
- `/openaccess/search` + `Ocp-Apim-Subscription-Key` 헤더 → 401

## 인증

- `api_key`를 **쿼리 파라미터**로 전달.
- `Accept: application/json` 헤더.

## 쿼리 파라미터

| 파라미터 | 설명 | 예시 |
|----------|------|------|
| `api_key` | API 키 | `?api_key=your_springer_api_key_here` |
| `q` | 키워드 검색어 (keyword: 접두사 필수) | `q=keyword%3A%20tauopathy` |
| `s` | 시작 위치 | `s=1` |
| `p` | 페이지 길이 (반환 건수) | `p=10` |

## 실제 응답 예시 (tauopathy 검색, 2건)

```json
{
  "apiMessage": "This JSON was provided by Springer Nature",
  "query": "keyword: tauopathy",
  "result": [
    {"total": "323", "start": "1", "pageLength": "2", "recordsDisplayed": "2"}
  ],
  "records": [
    {
      "contentType": "Article",
      "identifier": "doi:10.1186/s44477-026-00045-w",
      "url": [{"format": "", "platform": "", "value": "http://dx.doi.org/10.1186/s44477-026-00045-w"}],
      "title": "Proteomic analysis of human chronic traumatic encephalopathy brain implicates proteasome and ribosome dysfunction in disease severity",
      "creators": [
        {"creator": "Pennington, Helen E."},
        {"creator": "Shapiro, Dillon"},
        {"creator": "Empawi, Jenny"},
        {"ORCID": "0000-0002-0753-8992", "creator": "Labadorf, Adam"}
      ],
      "publicationName": "Molecular Neurodegeneration Advances",
      "doi": "10.1186/s44477-026-00045-w",
      "publisher": "Springer",
      "publisherName": "BioMed Central",
      "publicationDate": "2026-08-14",
      "publicationType": "Journal",
      "issn": "",
      "eIssn": "3059-4944",
      "volume": "2",
      "number": "1",
      "startingPage": "1",
      "endingPage": "15",
      "journalId": "44477",
      "openAccess": "true",
      "onlineDate": "2026-08-14",
      "coverDate": "2026-12",
      "copyright": "©2026 The Author(s)",
      "abstract": {
        "h1": "Abstract",
        "p": [
          "Background",
          "Chronic traumatic encephalopathy (CTE) is a neurodegenerative disease that occurs in individuals with repeated head impacts (RHI) exposure...",
          "Methods",
          "SomaScan 7k high-throughput proteomics was performed on 204 dorsolateral prefrontal cortex samples...",
          "Results",
          "Gene set enrichment analysis revealed that proteasome subunit proteins and related pathways were strongly associated with CTE severity...",
          "Conclusions",
          "These findings advance our understanding of the postmortem brain CTE molecular profile..."
        ]
      },
      "subjects": ["Biomedicine", "Neurosciences", "Neurology", "Molecular Medicine"],
      "disciplines": [{"id": "2935", "term": "Neuroscience"}, {"id": "2937", "term": "Neurology"}],
      "topicalCollection": "",
      "genre": ["OriginalPaper", "Research"]
    }
  ]
}
```

## 제한

- **Daily Quota:** 500 Hits/Day
- **Throttling:** 100 Hits/Min (분당 최대 요청 수)
- 429 시 `Retry-After` 헤더 기반 재시도 권장

## 참고 문서

- 공식: https://api.springernature.com/openaccess/json
