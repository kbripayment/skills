# Citation Verification Workflow — 실행 계획

연구 논문을 입력받아 Google Scholar에서 인용 논문을 수집하고, OpenAlex로 보강·정준화한 뒤 본문을 3-tier로 확보·필터링하고 scite MCP로 검증해 Obsidian에 저장하는 파이프라인. `SKILL.md v1.2.0`의 실행 계획서이며, SKILL.md가 정본(spec)이다.

**생성일**: 2026-09-05
**최종 수정**: 2026-09-09 (LLM env 설정 + RQ 분류 구현 + 수집 폴백 확정 반영)
**상태**: 코드 동기화됨 (2026-09-09 리뷰 기준)
**변경 사유**: citing 논문도 개별 .md로 저장, raw file(attachments/) 별도 관리, batch_progress.json 복구 지원. 이후 LLM API URL/모델 env화, RQ 3-class·verdict·review 큐 구현, SerpApi 우선 수집, stats/review_passages 출력 확정

---

## 전체 파이프라인 (6단계, SKILL.md와 동일)

```
[입력: title | doi | url]
        │
        ▼
┌──────────────────────────────────┐
│ ① 입력 정규화 & 대상 식별 + 정준화 │  web_extract / CrossRef / Scholar
│  - 입력 검증, DOI 우선, 일치 검증  │  유사도 ≥0.85 + 저자/연도
│  - 정준화: DOI>OpenAlexID>title   │  SHA256 중복 제거
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│ ② Scholar Cited by 수집          │  browser_exec
│  - Cited by N 클릭, 페이지네이션 │  10건/페이지, 최대 100건
│  - 1-3초 간격, 캡차 감지, 백오프  │
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│ ③ OpenAlex 메타데이터 보강       │  OpenAlex API + web_extract
│  - DOI/초록/OA URL 보강          │  polite pool (mailto)
│  - 피인용은 OpenAlex로 보완       │
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│ ④ 본문 확보 (3-tier 통합)        │  web_fetch → academic-mcp
│  Tier1: OA 직접 (arXiv/PMC)      │
│  Tier2: web_fetch 랜딩 재탐색     │
│  Tier3: academic-mcp paper_download│ MCP 정상 경로
│  실패 → abstract_only 강등        │
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│ ⑤ 텍스트 추출 + 유사 전개 필터   │  PyMuPDF/pdfplumber + LLM
│  - abstract/intro/conclusion     │  RQ/방법론 분류
│  - score 보존, human_review 큐   │
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│ ⑥ scite 검증 + Obsidian 저장     │  scite MCP + obsidian
│  - search/graph/editorialNotices │  evidence 보존
│  - 검증 라벨 + Inbox 저장         │
└──────────────────────────────────┘
```

> **이전 다이어그램의 분기(OA PDF 확보됨/아닌 경우)는 ④ 단일 3-tier로 통합됨. OA 여부는 Tier 선택 로직 내부에서 처리한다.**

---

## 단계별 상세

### ① 입력 정규화 & 대상 논문 식별 + 정준화

- **도구**: `web_extract`, CrossRef API, `browser_exec` (Scholar)
- **입력 검증**: 빈 문자열/잘못된 DOI(`10.xxxx/...` 패턴) 거부. URL은 `web_extract`로 `<meta name="citation_title">` / DOI 추출 시도.
- **DOI 우선**: DOI 있으면 CrossRef/OpenAlex로 제목 역조회 후 Scholar 검색어 생성. `doi:10.xxx` 직접 검색보다 제목 검색이 재현율 높음.
- **일치 검증**: Scholar 상위 5개에서 `레벤슈타인 유사도 ≥0.85 + 저자 성 일치 또는 연도 ±1`로 대상 확정. 불일치 시 후보 3개 사용자에게 제시 후 확인.
- **정준화/중복 제거** (remote_codex #1 반영, 코드 구현 확정):
  - Scholar와 OpenAlex가 동일 논문을 preprint/accepted/publisher로 중복 반환하는 문제 대응.
  - 정규화 키: `DOI(소문자·trim·https://doi.org/ 제거) > OpenAlex ID(W... ) > normalized(title+first_author+year)` — `dedupe_papers`로 수집 후 적용.
  - Version-of-record: `publisher_version > accepted_manuscript > preprint` 우선 — `enrich_paper`가 `locations[].version`으로 판별.
  - 제목 매칭: `fetch_openalex_by_title`이 상위 5건 중 정규화 제목 유사도(difflib)+연도 가산으로 최적 선택.
  - PDF 해시: 다운로드 후 SHA256 비교, 중복 시 메타 병합하고 `representative_pdf` 1건만 유지.
- **출력**: `canonical_input_paper {title, doi, openalex_id, year, version}` + 검증 로그

### ② Scholar Cited by 수집

- **도구**: `browser_exec` (`https://scholar.google.com`)
- **수집**: 대상 논문 행의 `Cited by N` 클릭 → 페이지네이션 순회. `max_citing_papers` 기본 50, 최대 100(안정 한계).
- **필드**: `title, authors[], year, citation_count, url_scholar, url_source, snippet`
- **중복 제거**: ①의 정준화 키로 즉시 dedup.
- **오류 처리**:
  - 캡차/차단 감지 시 즉시 중단, `{"status":"captcha_blocked","collected":[...],"next_action":"SerpApi 또는 OpenAlex cited_by_api_url 폴백"}` 반환.
  - 페이지 간 1-3초 랜덤 대기, 실패 시 지수 백오프(2s→4s→8s) 최대 3회.
  - 대체 경로 (코드 구현 확정): `SERPAPI_KEY` 있으면 SerpApi `cites` 우선 수집 → 실패/결과없음 시 OpenAlex `cited_by_api_url`로 폴백 (`references/api-alternative.md`). 전 구간 지수 백오프(2s→4s→8s, 3회) 적용 (`_get_with_backoff`). SerpApi 경로는 DOI 미제공 → OpenAlex 보강 단계에서 추정.
  - 페이지네이션 (코드 구현 확정): SerpApi `start` 루프(20건씩), OpenAlex `per-page=200&page=` 루프. `max_results` 도달·빈 페이지·미만 수신 시 종료.
- **출력**: `citing_candidates_raw[]` (정준화 전, 최대 100건)

### ③ OpenAlex 메타데이터 보강

- **도구**: `web_extract` + `https://api.openalex.org/works?filter=title.search:"..."` (+ `mailto` polite pool)
- **보강 항목**: `doi, abstract(inverted→text), publication_date, authorships, open_access.oa_url, primary_location, cited_by_api_url, referenced_works`
- **DOI 정확도**: 제목 검색 다건 시 `display_name` 유사도 + `publication_year` 일치로 1건 선택. DOI 없으면 이후 scite 검증 스킵하고 `verification: unverifiable_no_doi`.
- **피인용 보완**: Scholar에서 피인용(References) 직접 추출 불가 → OpenAlex `referenced_works`로 보완한다고 명시 (기존 plans의 "피인용도 수집" 모호성 해소).
- **출력**: `enriched_papers[]` (DOI/OA URL 보강, 정준화 키 확정)

### ④ 본문 확보 — 3-tier 통합 (기존 ③-1/③-2 중복 해소)

> **수정 사유**: 기존 ③-1(web-fetch)과 ③-2(academic-mcp)는 역할 중복. "FastMCP 직접 import" 서술은 MCP 프로토콜 우회 꼼수라 운영에서 제거.

**통합 전략 (단일 단계, 순차 폴백)**:

| Tier | 조건 | 도구 | 비고 |
|------|------|------|------|
| Tier1 | `open_access.oa_url` 존재 | `web_fetch` / `fetch` | arXiv, PMC 등 OA 직접 다운로드 |
| Tier2 | Tier1 실패 또는 oa_url 없음 | `web_extract` 랜딩 재탐색 → `web_fetch` | DOI 리졸버 페이지에서 PDF 링크 재탐색 |
| Tier3 | Tier2 실패 | `academic-mcp` `paper_download` | **MCP 정상 경로** `streamable_http_client + ClientSession.call_tool` ( `src/scite_client.py` 패턴). 직접 import는 디버그용으로만 허용 |
| Fallback | 모두 실패 | `abstract_only` | `acquisition_method: abstract_only`, 원문 미확인 명시 |

- **환경 변수**: Springer/ScienceDirect 등 구독 소스는 `Path.home() / ".hermes" / ".env"` 또는 `$HERMES_HOME`에서 API 키 로드. 절대경로 하드코딩 금지 (예: `C:\Users\user\...\research_new\.env` → 제거됨).
- **출력**: `pdf_path | null`, `acquisition_method: oa_direct | web_fetch | academic_mcp | abstract_only`, `pdf_sha256 | null`

### ⑤ 텍스트 추출 + 유사 전개 필터링

- **도구**: PyMuPDF(1순위, 속도) / pdfplumber(fallback, 레이아웃 보존) + LLM 분류
- **LLM 설정 (코드 구현 확정)**: `~/.hermes/.env`의 `LLM_API_KEY` + `LLM_API_URL` 사용. 해석 순서: 함수 인자 > env > 기본값(OpenAI URL). 기본 모델 `auto/best-reasoning` (`DEFAULT_LLM_MODEL`). 키가 없으면 결정적 휴리스틱으로 폴백 (오프라인 동작, related는 confidence=low → review 큐 유도).
- **게이트웨이 대응 (2026-09-09 실측 반영)**: 사내 게이트웨이가 `stream` 미요청에도 SSE 스트리밍으로 응답하므로 `_parse_chat_content`로 단일 JSON·SSE 양립 파싱. `max_tokens` 1000 (reasoning 추론 여유), reasoning 모델(`reasoning`/`thinking`/o1·o3·o4)은 `temperature` 제외, `stream: False` 명시, 숫자 추출은 마지막 float 우선. 실서버 검증: similarity `0.8`, 분류 `same/high/high` 수신 (review_citation.md 실호출 3차).
- **추출 범위**: `abstract + introduction + conclusion` (전체 본문 TF-IDF는 노이즈 많음)
- **필터 기준 (concrete)**:
  - RQ 동일성: 원본 RQ 1문장 요약 → 후보 RQ 추론 → LLM 3-class `same / related / unrelated` — `same + related(상위 50%)` 통과
  - 방법론 유사성: 키워드 Jaccard ≥0.3 또는 LLM `method_similarity: high/medium/low` 중 high/medium 통과
  - **프롬프트**:
    ```
    원본 RQ: "{original_rq}"
    후보 abstract+intro: "{candidate_text[:4000]}"
    Q1: 동일한 연구 질문인가? (same/related/unrelated)
    Q2: 방법론 유사도? (high/medium/low)
    Q3: 비슷한 전개로 볼 수 있는가? (yes/no + 1줄 근거)
    ```
  - TF-IDF cosine 보조 지표 ≥0.35, 최종 결정은 LLM 우선
- **재현성 규칙** (remote_codex #2 반영):
  - 모든 판정에 `filter_reason, rq_class, method_similarity, tfidf_score, confidence, verdict`를 JSON에 보존 (`classify_rq_similarity` + `decide_verdict`).
  - 판정표(코드 구현 확정): unrelated→`filtered_out`(항상 제외), confidence low→`needs_human_review`, method low→`filtered_out`, same+(score≥thr 또는 tfidf≥0.35)→`kept`, related+score≥thr→`kept`.
  - `filter_by_rq(include_review=True)`면 review 항목을 verdict와 함께 반환. `run_pipeline`은 kept만 저장하고 review는 `review_passages`로 분리, `stats.needs_review`에 집계. Obsidian 배지는 `review_needed`.
  - Inclusion/exclusion 기준 스냅샷을 매 실행 `log.md`에 기록. (코드 구현 확정: `write_run_log`가 SKILL_ROOT/`log.md`에 실행 스냅샷 append, 실패해도 파이프라인 계속.)
- **출력**: `filtered_papers[]` + `human_review_queue[]` + 텍스트 섹션

### ⑥ scite 검증 + Obsidian 저장

- **도구**: `src/scite_client.py:SciteClient` (`search_literature`, `citation_graph`, `editorialNotices`, `read_fulltext`)
- **검증 흐름** (코드 구현 확정):
  1. `search_literature(dois=[doi])` → 메타 존재 확인 + `tally{supporting/mentioning/contrasting}` + `citations[].snippet`
  2. `citation_graph` 교차 검증 + `unconfirmed_by_scite` 플래그. (코드 구현 확정: 수집 DOI 목록을 graph papers/edges 키 집합과 대조, 미포함분을 `unconfirmed_by_scite`에 기록. graph 실패 시 스킵. 수집(②)을 검증(⑥) 앞으로 이동.)
  3. `editorialNotices` → `retracted/corrected/concern` — retracted 최우선 경고. 라벨은 tally 비율 기반(`supporting/contrasting` 30% 기준)으로 결정, `evidence_excerpt`(첫 snippet), `source_version`, `retrieved_at`(ISO8601) 저장
- **검증 라벨** (코드 구현 확정): `verification_status`는 `verified | partially_verified | unverified | unverifiable_no_doi | retracted | scite_unreachable` (plans 어휘 통일). `label`은 tally 상세(`supporting/contrasting/mixed/unverified`) 유지. 토큰없음·예외→`scite_unreachable`, DOI없음→`unverifiable_no_doi` (단일+배치 공통)
- **scite 한계 명시** (remote_codex #3 반영):
  - scite 분류는 **인용 의도**(지지/언급/반박)이며 방법론·데이터·결론의 사실 검증이 아님. 커버리지 불완전/분야 편향 존재.
  - `verified`는 "scite에 인용 관계가 확인됨"을 의미. 사실 검증은 본문 대조 또는 replication/systematic review가 필요.
  - 모든 검증에 `evidence_excerpt`(스니펫 원문), `source_version`(DOI 버전), `retrieved_at`(ISO8601) 저장.
- **Obsidian 저장**: `obsidian` 스킬 + `web-grounded-note-taking` 패턴. Inbox에 통합 리포트 + (옵션) 논문별 노트. frontmatter: `verification, tally, citation_snippet, evidence_excerpt, retrieved_at, acquired_via, pdf_sha256, needs_review`
- **출력**: 검증 결과 + Obsidian 경로 목록

---

## 오류 처리 & 제한 사항

| 상황 | 대응 |
|---|---|
| Scholar 캡차/차단 | 즉시 중단, 부분 결과 반환, SerpApi/OpenAlex 폴백 제안 |
| 속도 제한 | 1-3초 랜덤 대기, 지수 백오프 3회 |
| 인용 1,000+ | Scholar 1,000건 이후 불안정 — 상위 100건 + 연도 필터 분할 수집 |
| DOI 없음 | scite 스킵, `unverifiable_no_doi`, snippet 요약만 |
| OA 아님 / PDF 없음 | `abstract_only` 강등, 원문 미확인 명시 |
| 언어 | 비영어 논문 스니펫 불완전 — 원문 언어 표기 |
| 네트워크/타임아웃 | `httpx` 60s, 다음 tier로 폴백, 부분 성공 저장 |
| 중복/버전 중복 | 정준화 키 + SHA256으로 제거 |

---

## 출력 형식 (SKILL.md와 동일)

### JSON

```json
{
  "input_paper": {"title":"...","doi":"10.xxxx/...","year":2024,"cited_by_count_scholar":42,"cited_by_count_scite":38, "openalex_id":"W..."},
  "citing_papers": [{
    "title":"...", "authors":["..."], "year":2023, "doi":"10.xxxx/...",
    "open_access_url":"https://arxiv.org/pdf/...",
    "url_scholar":"https://scholar.google.com/...", "snippet":"...",
    "acquisition_method":"oa_direct|web_fetch|academic_mcp|abstract_only",
    "pdf_path":"output/pdfs/...pdf|null", "pdf_sha256":"abc...|null",
    "filter_verdict":"kept|filtered_out|needs_human_review",
    "filter_reason":"RQ same, method high", "rq_class":"same", "method_similarity":"high", "tfidf_score":0.42,
    "scite":{"verification":"verified|...","tally":{"supporting":3,"mentioning":5,"contrasting":0,"total":8},"citation_snippet":"...","evidence_excerpt":"...","source_version":"v1","retrieved_at":"2026-09-05T00:00:00+09:00","editorialNotices":[]},
    "summary":"..."
  }],
  "stats":{"collected":50,"deduped":42,"with_doi":38,"with_pdf":22,"verified":30,"needs_review":5,"retracted_flagged":1},
  "review_passages": [{"section":"...","text":"...","score":0.3,"verdict":"needs_human_review","rq_class":"related","confidence":"low"}],
  "collected_at":"2026-09-05T00:00:00+09:00"
}
```

> 코드 구현 확정: `run_pipeline` 반환에 `review_passages[]` + `stats` 포함. Obsidian에는 kept만 저장.

### Obsidian 저장 정책 (v1.3.0)

#### 디렉토리 구조
```
{vault}/
├── attachments/                    ← 원본 raw file (PDF), 논문별 서브디렉토리
│   └── {year}/
│       └── {sha256[:8]}_{safe_title}.pdf
├── Inbox/
│   └── {year}/
│       ├── {normalized_title}.md     ← 메인 논문 노트
│       └── citing/
│           └── {normalized_title}.md ← citing 논문별 개별 노트
└── batch_progress.json            ← 배치 중단 복구용 진행 상태
```

#### Raw file 관리 (핵심)
- PDF/PDF-equivalent는 `{vault}/attachments/{year}/{sha256[:8]}_{safe_title}.pdf`에 **복사** 저장
- 파일명: SHA256 앞 8자 prefix + safe_title (DOI/제목 충돌 방지)
- 노트의 frontmatter `sha256` 필드로 attachments 경로 역추적 가능
- 노트 본문에 `![[attachments/{year}/{name}.pdf]]` 위키링크 삽입
- abstract_only(원문 없음)는 raw file 없이 sha256=null로 저장
- 중복 PDF 저장 방지: SHA256 사전 스캔으로 O(1) 조회

#### 논문별 .md 개별 저장
- 메인 논문 1건 + citing 논문 N건 → 각각 개별 .md
- citing 노트: `source_doi` (원논문 DOI) + `cites: [[원논문 타이틀]]` 백링크
- 원논문 노트: citing 목록은 `citing_papers` JSON blob로 frontmatter에 저장

#### Obsidian Properties (YAML frontmatter, Obsidian 호환)
```yaml
---
title: "..."
doi: "10.xxx/..."
year: 2024
authors: ["A", "B"]          # Obsidian Properties v2 배열 문법
openalex_id: "W..."
source: "openalex"
version: "published"
sha256: "abc..."              # attachments/ 연동
raw_pdf: "attachments/2024/abc12345_title.pdf"  # 상대경로
acquisition_method: "oa_direct"
acquisition_tier: 1
scite_label: "supporting"
scite_verification_status: "verified"
total_citations: 38
supporting: 12
mentioning: 20
contrasting: 6
passages_count: 5
source_doi: "10.yyy/..."      # ← citing 논문인 경우: 이 논문을 인용한 원논문 DOI
cites: [[원논문 타이틀]]       # ← citing 논문인 경우: 원논문 Obsidian 링크
tags: [citation-paper, scite-verified]
created: 2026-09-05T...
---
```

#### 중복 제거 전략
- 정규화 키: `DOI(소문자·trim) > OpenAlex ID > normalized(title+first_author+year)`
- Version-of-record: `publisher > accepted_manuscript > preprint`
- SHA256 사전 스캔 → `set(sha256s)` 메모리 적재 → O(1) 조회 (vault 전체 rglob 1회)
- 동일 제목 충돌 시: `{safe_title}_{sha256[:8]}.md` suffix로 구분

#### 배치 실행 & 복구
- `batch_pipeline.py`: citing_papers[] 순차 처리, `time.sleep(1.0)` throttle
- `{vault}/batch_progress.json`: `{"source_doi":..., "completed": [doi...], "failed": [...]}` 원자적 기록
- 중단 시: 완료된 DOI는 스킵하고 남은 것만 재개
- vault 용량 경고: PDF 4.4MB × 50건 ≈ 220MB膨胀

---

## 대안 API

- SerpApi(`cites`), Serply.io, OpenCitations COCI — `references/api-alternative.md` 참고. 차단 시 폴백 경로.

## 관련 스킬

- `grounded-citations`, `arxiv`, `research-paper-writing`, `obsidian`

---

## 변경 이력

- **2026-09-09**: 코드 동기화. LLM env(`LLM_API_KEY`/`LLM_API_URL`, 기본 모델 `auto/best-reasoning`), RQ 3-class·verdict·review 큐 구현, SerpApi 우선 수집+백오프, `review_passages`/`stats` 출력 확정 반영. 이후 F1(reasoning 게이트웨이) 해소: SSE 양립 파서 + `max_tokens` 1000 + reasoning `temperature` 제외, 실서버 검증 통과. 이후 F3–F9 반영: 정준화 강화(유사도 매칭·version·dedupe), `citation_graph` 교차검증+`unconfirmed_by_scite`, `log.md` 스냅샷, 양 경로 페이지네이션, 라벨 plans 어휘 통일. 미구현 잔여: browser_exec 실크롤링 (review_citation.md F5 일부).
- **2026-09-05 v1.2.0**: SKILL.md v1.2.0과 동기화. ③-1/③-2 → 3-tier 통합, 절대경로 제거, 정준화/해시 dedup, LLM 필터 재현성(큐/보존), scite 한계 명시, 오류 처리 표 추가. remote_codex 3지적 해소.
- **2026-09-05 v1.0**: 초기 6단계 계획 (중복 단계·모호 필터 포함)
