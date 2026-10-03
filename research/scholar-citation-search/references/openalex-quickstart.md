# OpenAlex 인용 분석 실전 패턴 (2026-09-05 검증)

OpenAlex API를 이용한 인용 논문 수집·정제 요약. `scholar-citation-search` 스킬의 ②~③단계 OpenAlex 경로 실전 참고자료.

---

## 1. 인용 논문 목록 조회 (올바른 API)

### ❌ 잘못된 패턴 (원 논문 메타데이터만 반환)
```
GET /works/W4224295368/cited_by?per_page=200
→ 원 논문 자체의 정보를 반환 (results 배열 없음)
```

### ✅ 올바른 패턴 (인용 논문 목록)
```
GET /works?filter=cites:W4224295368&per_page=200&sort=cited_by_count:desc
```

- `filter=cites:{openalex_id}` — 해당 논문을 인용한 논문들
- `per_page` 최대 200
- `page` — 페이지네이션 (총 건수가 200 초과 시)
- `sort=cited_by_count:desc` — 인용 순 정렬
- 응답: `{"meta": {"count": 300, ...}, "results": [...]}`

**예시 (Python urllib)**:
```python
import urllib.request, json

def fetch_openalex_citations(openalex_id, per_page=200, max_total=300):
    all_results = []
    page = 1
    while len(all_results) < max_total:
        url = f"https://api.openalex.org/works?filter=cites:{openalex_id}&per_page={per_page}&page={page}&sort=cited_by_count:desc"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        results = data.get('results', [])
        if not results:
            break
        all_results.extend(results)
        page += 1
        # 중복 제거
        seen = set()
        unique = []
        for r in all_results:
            doi = r.get('doi') or ''
            if doi not in seen:
                seen.add(doi)
                unique.append(r)
        all_results = unique
        if len(results) < per_page:
            break
    return all_results
```

---

## 2. Abstract inverted index → 텍스트 복원

OpenAlex는 abstract를 inverted index 형태로 반환:
```json
"abstract_inverted_index": {
  "macrophages": [0, 5, 12],
  "are": [1, 6],
  "innate": [2, 13]
}
```

**복원 코드**:
```python
def inverted_index_to_text(inv_index):
    if not inv_index:
        return ""
    words = []
    for word, positions in inv_index.items():
        for pos in positions:
            words.append((pos, word))
    words.sort(key=lambda x: x[0])
    return ' '.join(w[1] for w in words)
```

---

## 3. fields 주의사항 (타입 변동성)

OpenAlex 필드 중 일부는 dict 또는 str로 올 수 있음 — `isinstance` 체크 필수:

```python
# concepts 처리
concepts_raw = p.get('concepts', [])
concepts = []
for c in concepts_raw:
    if isinstance(c, dict):
        concepts.append(c.get('display_name', ''))
    elif isinstance(c, str):
        concepts.append(c)
concepts = concepts[:10]

# keywords도 동일 패턴
keywords_raw = p.get('keywords', [])
keywords = [k.get('display_name', '') if isinstance(k, dict) else k for k in keywords_raw]
keywords = keywords[:10]
```

---

## 4. OA 정보 추출

```python
best_oa = p.get('best_oa_location') or {}
oa_url = best_oa.get('landing_page_url', '') if isinstance(best_oa, dict) else ''
pdf_url = best_oa.get('pdf_url', '') if isinstance(best_oa, dict) else ''
is_oa = p.get('open_access', {}).get('is_oa', False) if isinstance(p.get('open_access'), dict) else False
```

---

## 5. 중복 제거 (DOI 기준)

```python
seen_dois = set()
unique_papers = []
for p in raw_results:
    doi = p.get('doi') or ''
    if doi in seen_dois:
        continue
    seen_dois.add(doi)
    unique_papers.append(p)
```

---

## 6. scite 검증

### 6.0 실행 전 상태 확인 (필수)

scite 호출 전에는 반드시 아래 3가지를 확인한다. 하나라도 실패하면 **scite 검증 자체를 스킵**하고 Obsidian에 `scite_unreachable` 라벨로 저장한다.

```bash
# ① 환경변수에 토큰이 로드됐는지 확인
python -c "import os; print(len(os.environ.get('SCITE_ACCESS_TOKEN') or ''))"
# 0이면 호출 불가 → ②로

# ② .env 파일에 토큰이 실제로 있는지 확인
cat "$HOME/.hermes/.env" | grep SCITE_ACCESS_TOKEN=
# 값이 있으면 → ③로. 없으면 재인증 필요

# ③ 토큰 유효성 확인 (REST로 probed)
python - << 'PY'
import urllib.request, json, os
token = os.environ.get("SCITE_ACCESS_TOKEN")
url = "https://api.scite.ai/tallies/10.1038/s41467-024-54372-1"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    print(f"✅ 토큰 유효, tally total={d.get('tally',{}).get('total')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:200]
    if e.code == 401 and "expired" in body:
        print("❌ 토큰 만료 — 재인증 필요")
    else:
        print(f"❌ HTTP {e.code}: {body}")
except Exception as ex:
    print(f"❌ 오류: {ex}")
PY
```

**결과별 조치**:
- 토큰 길이 0 + `.env`에 값 있음 → 환경변수 미로드. `terminal` 환경에서 재실행하거나, 스크립트에서 `load_token()`(파일 읽기)로 전환.
- 토큰 있음 + 401 expired → `.env`의 토큰이 만료됨. `paperworks/scite_oauth_auth.py` 실행으로 재인증 → 새 토큰 저장.
- 토큰 있음 + 200 OK → 정상. scite MCP 또는 REST로 검증 진행.

### 6.1 환경변수 vs .env 파일 문제

- `execute_code` 런타임에서는 `SCITE_ACCESS_TOKEN` 환경변수가 설정되지 않은 경우가 많다. `.env` 파일에 값이 있어도 Python `os.environ`에는 보이지 않는다.
- `src/scite_client.py:load_token()`은 환경변수 → 파일 순으로 읽으므로, 파일 기반 로딩에 의존할 수 있다. 단, 호출 전에 `load_token()` 결과 길이를 찍어 확인하고 로그를 남긴다.
- 가장 확실한 방법: `terminal`에서 venv python으로 직접 스크립트를 실행. 이 환경은 `.env`가 export된 상태면 환경변수도 살아있고, `load_token()`의 파일 읽기 폴백도 동작한다.

### 6.2 토큰 만료

- scite 액세스 토큰(JWT)은 만료된다. 만료 시 REST `/tallies/{doi}`가 **HTTP 401 `{"detail":"API token has expired"}`** 를 반환한다.
- MCP `SciteClient` 호출 시에도 401이 발생하지만 MCP 레이어 노이즈로 인해 판별이 어려울 수 있으므로, **먼저 REST로 토큰 유효성을 probed**한다.
- 갱신: `paperworks/scite_oauth_auth.py`(PKCE S256)로 재인증 실행 → 새 액세스 토큰이 `.env`에 저장됨. refresh_token이 함께 저장돼 있다면 자동 갱신 가능하나, refresh_token도 만료됐을 수 있으므로 재인증 스크립트가 실패할 경우 수동 브라우저 승인을 병행한다.

### 6.3 scite MCP 클라이언트 호출 실패 — mcp+anyio cancel scope 버그

- `SciteClient()` 컨텍스트 매니저 진입(`__aenter__`) 시 `streamable_http_client` + `ClientSession.initialize()` 호출에서 다음 오류 발생:
  ```
  RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
  ```
- `mcp 2.0.0 + anyio 4.14.2` 및 `mcp 2.1.1 + anyio 4.15.1` 모두에서 재현됨. asyncio cancel scope가 진입한 태스크와 다른 태스크에서 exit되려는 문제로, 단순 버전 업그레이드로는 해소되지 않았다.
- **우회**:
  1. **REST `/tallies/{doi}` 직접 호출**(urllib/httpx) — MCP 없이 tally만 확보할 때 유효. 단, 토큰 유효해야 하며 401이면 갱신 필요. `/works?dois=...`, `/works/{doi}`, `/citations?dois=...`는 scite 공개 REST에서 **404**이므로 사용하지 않는다.
  2. **실행 환경 변경**: `execute_code` 대신 `terminal`에서 venv python 스크립트 직접 실행. 동일 버그가 발생할 수 있으나 환경에 따라 결과가 다를 수 있다.
  3. asyncio 이벤트 루프를 `asyncio.new_event_loop()`로 생성 후 `loop.run_until_complete` + `finally: loop.close()` 패턴 시도. 일부 환경에서 도움이 될 수 있으나 보장되지 않는다.
- **권장 순서**: 매번 ① `load_token()` 길이 확인 → ② REST `/tallies/{input_doi}` 호출로 토큰 유효성 + 논문 존재 확인 → ③ 성공 시 tally + snippet 확보. MCP `SciteClient`는 citation_graph·editorialNotices 등 추가 데이터가 필요할 때만 시도하되, 실패할 수 있음을 감안하고 부분 결과로 저장한다.

### 6.4 scite REST API 엔드포인트 참고

| 엔드포인트 | 방법 | 상태 |
|---|---|---|
| `/tallies/{doi}` | GET (Bearer 토큰) | ✅ 유효 — tally 반환 |
| `/works?dois=...` | GET | ❌ 404 |
| `/works/{doi}` | GET | ❌ 404 |
| `/citations?dois=...` | GET | ❌ 404 |

즉 공개 REST로는 tally만 가져올 수 있고, 논문 메타데이터·인용 목록·편집 공지는 **MCP를 통해서만** 조회 가능하다. 따라서 MCP가 완전히 회피 불가능하며, REST는 MCP 불가 시 tally 확인을 위한 보조 수단이다.

### 6.5 Obsidian 라벨링 규칙

scite 검증 결과를 다음 라벨 중 하나로 저장한다:

| 라벨 | 조건 |
|---|---|
| `verified` | scite에 논문 존재 + tally 확보 + editorial notices 없음 |
| `partially_verified` | scite에 논문 존재 + tally 확보 + 일부 인용만 확인 |
| `unverified` | scite에 논문 존재하나 tally 0 또는 인용 정보 부족 |
| `unverifiable_no_doi` | DOI 없음 — scite 조회 불가 |
| `retracted` | editorialNotices에 retracted 확인 |
| `concern_raised` | editorialNotices에 corrected/concern 확인 |
| `scite_unreachable` | 토큰 만료·mcp 버그·네트워크 등으로 검증 자체가 안 됨 (**검증 실패가 아니라 검증 미수행**) |

`scite_unreachable`은 "실패"가 아니다. 추후 토큰 갱신·재인증 후 재실행 가능한 상태로 남겨둔다. 모든 결과에 `evidence_excerpt`(인용 스니펫 원문), `source_version`(DOI 버전), `retrieved_at`(ISO8601), `acquired_via` 필드를 저장한다.
