# Springer Nature API — 실시간 검증 결과

## 검증일: 2026-08-19

## API 엔드포인트

| API 종류 | URL | 쿼리 형식 |
|---------|-----|----------|
| **Open Access** | `https://api.springernature.com/openaccess/search` | `q="cancer immunotherapy"`, `p=3`, `s=1` |
| **Meta** | `https://api.springernature.com/meta/search` | 동일 |
| **TDM** | `https://api.springernature.com/tdm/search` | 동일 |

## 인증 방식

- 헤더: `Ocp-Apim-Subscription-Key: <api_key>`
- 환경 변수: `SPRINGER_API_KEY`

## Rate Limit

| 제한 종류 | 값 | 비고 |
|----------|-----|------|
| **Daily Quota** | 500 Hits/Day | API key당 24시간 기준 |
| **Throttling** | 100 Hits/Min | 분당 최대 요청 수 |

## 응답 구조 (Open Access)

```json
{
  "messages": [{"status": "success", ...}],
  "records": [
    {
      "title": "...",
      "doi": "...",
      "url": "...",
      "abstract": "...",
      "creators": [{"name": "Author, A."}],
      "datePublished": "2024-01-01",
      "landingPageUrl": "https://link.springer.com/article/..."
    }
  ]
}
```

## GitHub 래퍼

- Repository: https://github.com/springernature/springernature_api_client
- PyPI: `pip install springernature_api_client`
- 사용법:

```python
import springernature_api_client.openaccess as openaccess
client = openaccess.OpenAccessAPI(api_key="your_api_key")
response = client.search(q='keyword:"cancer immunotherapy"', p=20, s=1)
```

## Rate Limit 대응 패턴 (검증 완료)

```python
for attempt in range(3):
    r = requests.get(base_url, params=params, headers=headers, timeout=60)
    if r.status_code == 429:
        retry_after = int(r.headers.get("Retry-After", "60"))
        time.sleep(retry_after)
        continue
    if r.status_code == 403:
        # API key 오류 - 즉시 중단
        return []
    r.raise_for_status()
    break
```

## 주의사항

1. API key가 없으면 스킵 (warning 로그만 출력)
2. 403 응답 = API key 무효 또는 daily quota 초과
3. 429 응답 = Throttling 제한 → `Retry-After` 헤더 기반 재시기
4. `q` 파라미터에 따옴표로 정확 매칭 (`q="cancer immunotherapy"`)
5. **Throttling 100 Hits/Min 대응**: 호출 간 최소 0.7초 대기 (`time.sleep(0.7)`) 권장