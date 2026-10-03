---
name: scholar-citation-search
description: >
  논문 제시 시 Google Scholar/ OpenAlex/ scite를 연계해 인용·피인용 논문을
  수집·검증·요약하고 Obsidian에 저장하는 스킬.
version: 1.2.0
last_updated: 2026-09-05
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Google Scholar, Citation, Paper Search, Summary, Verification]
    category: research
    related_skills: [grounded-citations, arxiv, research-paper-writing, obsidian]
    requires:
      tools: [browser_exec, web_extract, web_fetch]
      mcp: [scite, academic-mcp]
      env: [SCITE_ACCESS_TOKEN]
    optional_env: [OPENALEX_MAILTO, SERPAPI_KEY]
---

# Scholar Citation Search

연구 논문(제목 / DOI / URL)을 입력받아 **Google Scholar Cited by**를 1차 수집원으로,
**OpenAlex + scite MCP**를 검증 계층으로 결합해 인용 논문을 수집·필터링·검증·요약한다.

> **설계 원칙**: Scholar는 탐색용(넓게), OpenAlex/scite는 검증용(정확하게).
> DOI가 있으면 scite가 진실원천, 없으면 OpenAlex 메타데이터로 보강 후 snippet 기반 제한 요약.

## 언제 사용

- "이 논문을 인용한 논문들 찾아줘" / "후속 연구 동향 정리해줘"
- 특정 논문의 학술적 영향력·피인용 맥락·retraction 여부를 확인
- 논문 제목/DOI/URL 중 하나만으로 Cited by 목록 추출 + 검증

## When to Use (EN)

- "Find papers citing this paper" / "What's the citation impact of X?"
- Trace follow-up work, verify citation context, check for retractions.

---

## 사전 준비

| 구분 | 필요 여부 | 내용 |
|---|---|---|
| `browser_exec` | 필수 | Hermes Browser Use 활성화. Scholar는 JS 렌더링 + 봇 차단으로 단순 HTTP 불가 |
| `SCITE_ACCESS_TOKEN` | 권장 | scite MCP OAuth 토큰. `~/.hermes/.env` 또는 환경변수에서 로드 (`src/scite_client.py:load_token()` 참고). 플랫폼 독립 경로 사용 — 절대 하드코딩 금지 |
| `academic-mcp` | 권장 | OA 외 논문 PDF 다운로드 fallback (`paper_download`) |
| `OPENALEX_MAILTO` | 선택 | OpenAlex polite pool용 이메일. 없으면 anon 요청 |
| `SERPAPI_KEY` 등 | 선택 | 브라우저 차단 시 대체 경로. `references/api-alternative.md` 참고 |

> **경로 규칙**: `C:\Users\...\.env` 같은 절대경로 하드코딩 금지. `Path.home() / ".hermes" / ".env"` 또는 `$HERMES_HOME` 환경변수를 사용한다.

---

## 파이프라인 (6단계, plans_citation.md 통합)

```
[입력: title | doi | url]
        │
        ▼
┌──────────────────────────────┐
│ ① 입력 정규화 & 대상 논문 식별 │  web_extract / CrossRef / Scholar 검색
│  - DOI→제목 역조회, URL→메타 추출 │
│  - Scholar에서 제목·저자·연도 일치 검증 │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ② Scholar Cited by 수집      │  browser_exec
│  - "Cited by N" 클릭, 페이지네이션 │
│  - 제목/저자/연도/인용수/링크/스니펫 추출│
│  - 중복 제거, 최대 100건, 1-3초 간격 │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ③ OpenAlex 메타데이터 보강   │  web_extract + OpenAlex API
│  - 제목 기반 검색 → DOI/초록/OA PDF 링크 확보 │
│  - published_date, authorships, is_oa 보강 │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ④ 본문 확보 (3-tier fallback)│  web_fetch → academic-mcp
│  Tier1: OA PDF 직접 다운로드 (arXiv/PMC) │
│  Tier2: web_fetch으로 pdf_url 추출 시도 │
│  Tier3: academic-mcp paper_download (arXiv/PubMed/PMC/SS) │
│  실패 시 abstract/snippet 기반 제한 요약으로 강등 │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ⑤ 텍스트 추출 + 유사 전개 필터│  PyMuPDF / pdfplumber + LLM
│  - abstract/intro/conclusion 추출 │
│  - 연구질문·방법론·평가 유사도 분류 │
│  - 임계값/프롬프트는 아래 상세 참고 │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ⑥ scite 검증 + Obsidian 저장 │  scite MCP + obsidian 스킬
│  - search_literature / citation_graph / editorialNotices │
│  - 검증 상태 라벨링 후 Obsidian Inbox 저장 │
└──────────────────────────────┘
```

### 단계별 상세

#### ① 입력 정규화 & 대상 논문 식별 + 정준화(deduplication)

- **입력 검증**: 빈 문자열/잘못된 DOI 형식(`10.xxxx/...`) 거부, URL은 `web_extract`로 제목/DOI 추출 시도.
- **DOI 우선**: DOI가 있으면 CrossRef/OpenAlex로 제목 확인 후 Scholar 검색어 생성 (`"doi:10.xxx"`보다 제목 검색이 안정적).
- **일치 검증**: Scholar 결과 상위 5개에서 제목 레벤슈타인 유사도 ≥0.85 + 저자 성 일치 또는 연도 ±1년으로 대상 논문 확정. 불일치 시 사용자에게 후보 3개 제시 후 확인.
- **정준화/중복 제거 (remote_codex 지적 반영)**: Scholar와 OpenAlex가 동일 논문을 preprint/accepted/publisher 3종으로 중복 반환하는 문제 대응. 키 우선순위 `DOI(정규화: 소문자, trim) > OpenAlex ID > title+first_author+year` 로 정규화. Version-of-record 정책: `publisher_version > accepted_manuscript > preprint` 우선. PDF는 SHA256 해시로 중복 제거, 중복 시 메타는 병합하고 `representative_pdf` 1건만 유지.

#### ② Scholar Cited by 수집

- **도구**: `browser_exec` (`https://scholar.google.com`)
- **수집**: `Cited by N` 클릭 → 결과 페이지 순회. 한 페이지 10건, `max_citing_papers` 기본 50, 최대 100 (안정 한계).
- **필드**: `title, authors, year, citation_count, url_scholar, url_source, snippet`
- **신뢰도 처리**: Scholar 차단/캡차 감지 시 즉시 중단, 사용자에게 `{"status":"captcha_blocked","collected": [...]}` 반환. 재시도는 지수 백오프(2s,4s,8s) 최대 3회.
- **대체 경로**: 차단 지속 시 SerpApi `cites` 파라미터 또는 OpenAlex `cited_by_api_url`로 폴백 (API 키 있을 때만).

> **⚠️ OpenAlex 인용 논문 API 주의 (2026-09-05 발견)**: `/works/{id}/cited_by` 엔드포인트는 인용 논문 목록이 아니라 **원 논문 자체 메타데이터**를 반환한다. 인용 논문 목록을 OpenAlex API로 직접 수집하려면 `/works?filter=cites:{openalex_id}` 형태를 사용해야 한다. 예: `https://api.openalex.org/works?filter=cites:W4224295368&per_page=200&sort=cited_by_count:desc`. `per_page` 최대 200, 총 건수가 200 초과 시 `page` 파라미터로 페이지네이션.

#### ③ OpenAlex 메타데이터 보강

- **도구**: `web_extract` + `https://api.openalex.org/works?filter=title.search:"..."`
- **보강 항목**: `doi, abstract (inverted→text), publication_date, authorships, open_access.oa_url, primary_location`
- **DOI 정확도**: 제목 검색 결과가 다수일 때 `display_name` 유사도 + `publication_year` 일치로 1건 선택. DOI 없으면 이후 단계에서 scite 검증 스킵하고 `verification: "unverifiable_no_doi"` 라벨.

#### ④ 본문 확보 (통합 — 기존 plans의 ③-1/③-2 중복 해소)

> **문제**: plans_citation.md의 ③-1(web-fetch)과 ③-2(academic-mcp)는 역할이 중복되고, "FastMCP 직접 호출" 서술은 MCP 프로토콜을 우회하는 불안정한 꼼수다.

**통합 전략 (단일 단계, 3-tier)**:

1. **Tier1 OA 직접**: `open_access.oa_url` 있으면 `web_fetch` 또는 `fetch`로 PDF 직접 저장.
2. **Tier2 web_fetch 추출**: `pdf_url`이 없거나 실패 시 `web_extract`로 랜딩 페이지에서 PDF 링크 재탐색.
3. **Tier3 academic-mcp**: 상기 실패 시 `paper_download` 호출 (MCP 프로토콜 정상 경로, `src/scite_client.py`처럼 `ClientSession.call_tool` 사용). Python 직접 import 꼼수는 디버그용으로만 허용, 운영 경로는 MCP 호출로 통일.

- **출력**: `pdf_path | null` + `acquisition_method: "oa_direct" | "web_fetch" | "academic_mcp" | "abstract_only"`
- **브라우저**: Springer/ScienceDirect 등 구독 필요 소스는 `.env`의 API 키가 있을 때만 시도, 없으면 `abstract_only`로 강등하고 로그에 기록.

#### ⑤ 텍스트 추출 + 유사 전개 필터링

- **도구**: PyMuPDF (1순위, 속도) / pdfplumber (fallback, 레이아웃 보존) + LLM 분류
- **추출 범위**: `abstract + introduction + conclusion` (전체 본문 TF-IDF는 노이즈 많음).
- **필터 기준 (concrete) — 재현성 보강**:
  - `연구 질문 동일성` (RQ overlap): 원본 RQ를 1문장 요약 → 각 후보 논문의 RQ 추론 → LLM 3-class 분류 (`same / related / unrelated`). `same` + `related(상위 50%)`만 통과.
  - `방법론 유사성`: 방법론 키워드 Jaccard ≥0.3 또는 LLM `method_similarity: high/medium/low` 중 high/medium 통과.
  - **임계값 예시 프롬프트**:
    ```
    원본 RQ: "{original_rq}"
    후보 논문 abstract+intro: "{candidate_text[:4000]}"
    Q1: 후보 논문이 원본과 동일한 연구 질문을 다루는가? (same/related/unrelated)
    Q2: 방법론이 유사한가? (high/medium/low)
    Q3: 이 논문을 "비슷한 전개"로 볼 수 있는가? (yes/no + 1줄 근거)
    ```
  - TF-IDF cosine은 보조 지표(≥0.35)로만 사용, 최종 결정은 LLM 분류 우선.
  - **운영 규칙 (remote_codex 지적 반영)**: 모든 판정은 `filter_reason`, `rq_class`, `method_similarity`, `tfidf_score`를 JSON에 보존. `related` 중 하위 50% 및 LLM 불확실(`confidence: low`)건은 `needs_human_review` 큐로 분리 — 자동 탈락시키지 않고 Obsidian에서 `review_needed` 배지로 표시. Inclusion/exclusion 기준은 실행마다 `log.md`에 스냅샷 저장해 재현성 확보.

#### ⑥ scite 검증 + Obsidian 저장

- **도구**: `src/scite_client.py:SciteClient` (`search_literature`, `citation_graph`, `editorialNotices`)
- **검증 흐름**:
  1. `search_literature(dois=[doi])` → 메타 존재 확인 + `tally {supporting/mentioning/contrasting}` + `citations[].snippet` 확보
  2. `citation_graph(seeds=[input_doi], direction="in", max_edges=limit)` → Scholar 수집 목록과 교차 검증. Scholar에는 있으나 graph에 없으면 `unconfirmed_by_scite` 플래그.
  3. `editorialNotices` → `retracted / corrected / concern` 확인. retracted면 최우선 경고 라벨.
- **검증 라벨**: `verified | partially_verified | unverified | unverifiable_no_doi | retracted | concern_raised`
- **scite 한계 명시 (remote_codex 지적 반영)**: scite 분류는 *인용 의도*(지지/언급/반박)이며 방법론·데이터·결론의 사실 검증이 아님. 커버리지 불완전/분야 편향 존재. 따라서 `verified`는 "scite에 인용 관계가 확인됨"을 의미하고, 사실 검증은 본문 대조 또는 replication/systematic review 필요. 모든 검증 결과에 `evidence_excerpt`(인용 스니펫 원문), `source_version`(DOI 버전), `retrieved_at`(ISO8601) 필드를 저장해 Obsidian에서 추적 가능하게 한다.
- **Obsidian 저장**: `obsidian` 스킬 + `web-grounded-note-taking` 패턴. Inbox에 1) 통합 리포트 + 2) 논문별 노트(옵션) 생성. frontmatter에 `verification, tally, citation_snippet, evidence_excerpt, retrieved_at, acquired_via` 포함.

---

## 출력 형식

### JSON (machine-readable)

```json
{
  "input_paper": {
    "title": "...",
    "doi": "10.xxxx/...",
    "year": 2024,
    "cited_by_count_scholar": 42,
    "cited_by_count_scite": 38
  },
  "citing_papers": [
    {
      "title": "...",
      "authors": ["..."],
      "year": 2023,
      "citation_count_scholar": 12,
      "doi": "10.xxxx/...",
      "open_access_url": "https://arxiv.org/pdf/...",
      "url_scholar": "https://scholar.google.com/scholar?...",
      "url_source": "https://doi.org/...",
      "snippet": "...",
      "acquisition_method": "oa_direct | web_fetch | academic_mcp | abstract_only",
      "pdf_path": "output/pdfs/...pdf | null",
      "filter Verdict": "kept | filtered_out",
      "filter_reason": "RQ same, method high",
      "scite": {
        "verification": "verified | partially_verified | ...",
        "tally": {"supporting": 3, "mentioning": 5, "contrasting": 0, "total": 8},
        "citation_snippet": "As shown in Smith et al. (2024)...",
        "citation_section": "Introduction",
        "editorialNotices": []
      },
      "summary": " grounded summary with citations..."
    }
  ],
  "summary_total": "전체 동향 요약...",
  "stats": {
    "collected": 50, "with_doi": 38, "with_pdf": 22,
    "verified": 30, "retracted_flagged": 1
  },
  "collected_at": "2026-09-05T00:00:00+09:00"
}
```

### Markdown / Obsidian

- `output/scholar-citations-YYYY-MM-DD.md` — 사람이 읽는 요약 리포트
- `Obsidian Inbox/scholar/<slug>.md` — frontmatter 포함 개별 노트 (검증 상태 배지, 인용 문맥 인용구)

---

## 실행 방식

```python
# execute_code 내 예시 (pseudocode) — MCP는 반드시 ClientSession.call_tool 경로 사용
from scite_client import SciteClient
from pathlib import Path

async def scholar_citation_search(paper_title: str, max_citing_papers=50):
    # ① 입력 정규화
    # ② browser_exec: scholar.google.com → Cited by 수집 (간격 1-3s, 캡차 감지)
    # ③ OpenAlex 보강
    # ④ 3-tier 본문 확보 (oa → web_fetch → academic-mcp)
    # ⑤ PyMuPDF 추출 + LLM 필터
    # ⑥ scite 검증 + Obsidian 저장
    async with SciteClient() as scite:
        paper = await scite.paper_by_doi(doi)
        graph = await scite.citing_papers(doi, limit=max_citing_papers)
        ...
```

> **주의**: `academic-mcp`의 searcher/downloader를 Python 직접 import하는 방식은 디버그 탐사용으로만 사용. 운영 코드는 MCP 프로토콜(`streamable_http_client` + `ClientSession`)을 따른다 — `src/scite_client.py` 패턴을 재사용.

---

## 제한 사항 & 오류 처리

| 상황 | 대응 |
|---|---|
| Scholar 캡차/차단 | 즉시 중단, 부분 결과 반환, 사용자에게 알림. SerpApi/OpenAlex 폴백 제안 |
| 속도 제한 | 페이지 간 1-3초 랜덤 대기, 지수 백오프 재시도 3회 |
| 인용 1,000+ | Scholar는 1,000건 이후 불안정 — 상위 100건 + 연도 필터 분할 수집 권장 |
| DOI 없음 | scite 검증 스킵, `unverifiable_no_doi` 라벨, snippet 기반 요약만 제공 |
| OA 아님 / PDF 없음 | `abstract_only`로 강등, "원문 미확인" 명시 |
| 언어 | 영어 외 논문은 스니펫 요약 불완전 가능 — 원문 언어 표기 |
| 네트워크/타임아웃 | `httpx` timeout 60s, 실패 시 다음 tier로 폴백, 전체 파이프라인은 부분 성공으로 저장 |

### scite 인증 & 토큰 관리 (2026-09-07 세션 발견)

> scite MCP는 Scholar/OpenAlex 수집 후 검증 계층으로 쓰지만, **토큰 만료·인증 버그·호출 실패가 빈발**하므로 실행 전에 반드시 연결 상태를 확인한다.

**① 토큰 로딩 & 환경변수 문제**
- `src/scite_client.py:load_token()`은 (a) `SCITE_ACCESS_TOKEN` 환경변수 → (b) `~/.hermes/.env` 파일 순으로 읽는다.
- **함정**: Hermes 세션에서 `.env` 파일에 토큰이 있어도 **환경변수로 export되지 않으면** `os.environ.get("SCITE_ACCESS_TOKEN")`가 빈 문자열을 반환한다. 이 경우 `SciteClient()`가 "토큰 없음" 오류를 내거나, 토큰이 있는 줄 알고 토큰 길이 0 상태로 연결 시도→실패한다.
- **확인**: 실행 전 `python -c "import os; print(len(os.environ.get('SCITE_ACCESS_TOKEN') or ''))"` 또는 `load_token()` 결과 길이를 찍어본다. 0이면 호출 불가.
- **해결**: (a) 세션 시작 스크립트에 `.env` export 로직을 넣거나, (b) `load_token()`이 파일을 읽도록 보장하고 호출 전에 로그를 남긴다.

**② 토큰 만료**
- scite 액세스 토큰(JWT)에는 유효기간이 있다. 만료되면 scite REST `/tallies/{doi}` 호출 시 **HTTP 401 `{"detail":"API token has expired"}`** 응답.
- **확인**: `curl -H "Authorization: Bearer $TOKEN" https://api.scite.ai/tallies/10.1038/...` 또는 `python urllib`으로 probed. 401 + 해당 메시지가 오면 만료.
- **해결**: `paperworks/scite_oauth_auth.py` (PKCE S256) 또는 scite MCP OAuth 플로우로 **재인증 → 새 액세스 토큰 → `.env` 갱신**. refresh_token이 `.env`에 있다면 자동 갱신 가능하나 만료됐을 수 있음.
- **참고**: scite MCP 클라이언트로 `paper_by_doi` 호출 시 401이 MCP 레이어에서 노이즈로 나올 수 있으므로, 먼저 REST로 토큰 유효성을 probed 하는 것이 빠르다.

**③ scite MCP 클라이언트 호출 실패 (mcp+anyio cancel scope 버그)**
- `SciteClient()`의 `__aenter__`에서 `streamable_http_client` + `ClientSession.initialize()` 호출 시, 다음과 같은 cancel scope 오류가 발생할 수 있음:
  ```
  RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
  ```
- 이것은 `mcp<=2.1.1` + `anyio>=4.14`의 asyncio 백엔드 cancel scope 교차 태스크 exit 문제로, **mcp 업그레이드(2.0.0→2.1.1) 및 anyio 업그레이드(4.14.2→4.15.1)로도 재현**됨.
- **우회 전략 (우선순위 순)**:
  1. **scite REST API 직접 호출로 대체**: `/tallies/{doi}` 엔드포인트가 유효하면 MCP 없이 urllib/httpx로 tallies를 가져온다. 단, **토큰 유효해야 하고**, `401 expired` 시 갱신 필요. `/works?dois=...`, `/works/{doi}`, `/citations?dois=...`는 scite 공개 REST에서 **404**이므로 사용하지 않는다.
  2. **실행 환경 변경**: `execute_code` 런타임(asyncio 이벤트 루프 정책 이슈) 대신 **terminal에서 venv python으로 직접 스크립트 실행**. 동일 cancel scope 버그가 발생할 수 있으나, 일부 환경에선 다르게 동작할 수 있음.
  3. **asyncio 이벤트 루프 재구성**: `asyncio.new_event_loop()` + 명시적 `loop.run_until_complete` + `finally: loop.close()` 패턴으로도 재현된 사례가 있음. cancel scope 문제는 루프 정책보다 anyio 내부 생성 태스크와 `async with` 종료 시점의 태스크 불일치가 원인으로 보이며 근본적 해결은 라이브러리 패치 대기.
- **권장 실행 순서**: 매번 scite 검증 전에 ① 토큰 로딩 확인 → ② REST `/tallies/{input_doi}`로 토큰 유효성 + 논문 존재능 확인 → ③ 성공 시 tallies + citation snippet 확보. MCP `SciteClient`는 ②가 실패하거나 더 풍부한 데이터(`citation_graph`, `editorialNotices`)가 필요할 때만 시도하되, ③도 실패할 수 있음을 감안하고 부분 결과로 저장한다.
- **Obsidian 저장 시**: scite 검증 결과를 `verified | partially_verified | unverified | unverifiable_no_doi | retracted | concern_raised | scite_unreachable` 라벨로 기록한다. `scite_unreachable`은 토큰 만료·mcp 버그·네트워크 등으로 검증 자체가 안 된 경우로, "검증 실패"가 아니라 "검증 미수행"으로 구분해야 한다.
- **scite tally 해석 시 주의**: 응답의 `total`(분류 완료된 인용 수)과 `citingPublications`(scite가 인지한 고유 인용 출판물 수)는 다른 값일 수 있다 (예: `total:8, citingPublications:12`). 200 OK에 `total:0`이 와도 "scite에 미등록"이 아니라 "아직 분류 인용이 없음"일 수 있으므로, HTTP 상태만으로 등록 여부를 판단하지 말고 `total` 필드를 본다.

> **scite 한계 (remote_codex 지적 반영, 유지)**: scite 분류는 *인용 의도*(지지/언급/반박)이며 방법론·데이터·결론의 사실 검증이 아님. 커버리지 불완전/분야 편향 존재. `verified`는 "scite에 인용 관계가 확인됨"을 의미, 사실 검증은 본문 대조 필요. 모든 결과에 `evidence_excerpt`(인용 스니펫 원문), `source_version`(DOI 버전), `retrieved_at`(ISO8601), `acquired_via` 필드 저장.

---

## 대안 API (선택)

API 키가 있을 경우 브라우저 대신 API 방식으로 ①~②를 대체:

- **SerpApi** (`cites` 파라미터), **Serply.io**, **OpenCitations COCI** — 비교표는 `references/api-alternative.md` 참고

---

## OpenAlex 실전 참고

OpenAlex API로 인용 논문 목록 수집·정제 시 실전 패턴 (역색인 abstract 복원, 필드 타입 변동성 처리, 중복 제거 등):

- `references/openalex-quickstart.md` — 검증된 코드 패턴 + pitfall 모음 (2026-09-05 세션 검증)

---

## 관련 스킬

- `grounded-citations` — 요약 시 출처 표기 스타일
- `arxiv` — arXiv 선행 연구 확장
- `research-paper-writing` — 리뷰/보고서 작성
- `obsidian` — Inbox 저장 패턴

---

## 변경 이력

- **1.2.0 (2026-09-05)**: `plans_citation.md`와 동기화. 정준화/중복제거(DOI 정규화+SHA256), LLM 필터 재현성(`needs_human_review` 큐, score 보존), scite 한계 명시(`evidence_excerpt/retrieved_at`), 3-tier 본문 확보 통합. remote_codex 3대 지적 반영.
- **1.1.0**: 6단계 파이프라인 통합, 경로 하드코딩 제거, 오류 처리 표 추가.
- **1.0.0**: 초기 4단계 Scholar 전용 파이프라인.
