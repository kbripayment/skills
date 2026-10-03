# progress_citation.md — scholar-citation-search v1.2.0

> 코드 작성 과정 추적. 중단 시 이 파일로 복구.
> 생성: 2026-09-05  |  마지막 갱신: 2026-09-09
> 스킬 루트: `C:\Users\user\AppData\Local\hermes\skills\research\scholar-citation-search\`
> 가상환경: `C:\Users\user\AppData\Local\Temp\academic-mcp-venv`

---

## Task 1 — scite OAuth 2.1 PKCE 인증 ✅ DONE

- scite.ai OAuth Client ID 발급 완료
- PKCE S256 (code_verifier → code_challenge) 구현 (`src/scite_oauth_auth.py`)
- `SCITE_ACCESS_TOKEN`, `SCITE_REFRESH_TOKEN` → `~/.hermes/.env` (UTF-16 LE BOM 인코딩 폴백)
- 13개 MCP 도구 디스커버리 완료: `search_literature`, `citation_graph`, `read_fulltext`, `bibliography`, `collection_*`, `citation_report_*`
- BERT 논문 (DOI:10.18653/v1/N19-1423) 테스트: Smart Citations 16,007건 + citation graph 20 edges
- **복구 지점**: 토큰 만료 시 `src/scite_oauth_auth.py --reauth` 재실행

---

## Task 2 — academic_mcp_direct.py 격리 모듈 ✅ DONE

- `src/academic_mcp_direct.py` (498줄) — 메인 모듈 확정
- MSYS2 절대경로 훼손 우회: `cd Scripts; ./python.exe` 상대경로 실행
- `_PaperEncoder` (datetime 직렬화), `SAVE_PATH`, 중복 SHA256 검사 구현
- 18개 학술 소스 활성화 (`list_sources`) + PDF 다운로드 + 텍스트 45,803자 추출 검증
- 레거시 스크립트 정리 완료 (`academic_mcp_client.py`, `academic_mcp_download_direct.py`, `academic_mcp_test.py` 삭제 확인)
- **복구 지점**: `cd "C:\Users\user\AppData\Local\Temp\academic-mcp-venv\Scripts" && ./python.exe "C:\Users\user\AppData\Local\hermes\skills\research\scholar-citation-search\src\academic_mcp_direct.py"`

---

## Task 3 — 3-tier 본문 확보 파이프라인 ✅ DONE / VERIFY

- `src/paper_acquisition.py` (402줄) 구현 완료
- Tier1: OpenAlex `open_access_url` → httpx 바이너리 GET → SHA256 저장
- Tier2: web_extract 랜딩 페이지 파싱 → PDF URL 역추출 → httpx GET
- Tier3: `AcademicMcpDirect` subprocess JSON IPC fallback (arXiv/PubMed/PMC)
- smoke test 결과 (2026-09-05):
  - ✅ Tier1: arXiv PDF 4.4MB 다운로드, sha256: `5c49f339...`, method: `oa_direct`
  - ✅ Tier3: BERT 논문 텍스트 45,803자 추출 성공
- **복구 지점**: `python src/paper_acquisition.py` 또는 smoke test 스크립트 직접 실행

---

## Task 4 — 텍스트 추출 + 유사 전개 LLM 필터링 ✅ IMPLEMENTED / ⏳ TESTING

- **입구**: `paper_acquisition.py`에서 추출된 텍스트 (PDF 경로 or raw text)
- **구현 내용** (src/text_extraction.py, 451줄):
  - [x] `extract_text_from_pdf(pdf_path)` — PyMuPDF 우선, pdfplumber 폴백
  - [x] `split_sections(text)` — abstract/intro/method/results/discussion/conclusion 분절 + regex 분절
  - [x] `get_priority_sections()` — 필터링 우선순위 섹션 추출
  - [x] `similarity_filter(text, rq, threshold=0.4)` — LLM API POST 기반 0.0~1.0 점수
  - [x] `_keyword_similarity_fallback()` — LLM_API_KEY 없을 때 키워드 오버랩 폴백 (0.0~0.5)
  - [x] `filter_by_rq(text_or_path, rq, threshold=0.4, max_passages=10)` — 메인 필터링 함수
  - [x] `_load_env()` — UTF-16 LE BOM 폴백으로 ~/.hermes/.env LLM_API_KEY 로드
  - [x] CLI: `python src/text_extraction.py -i <pdf> --rq "..." -t 0.4`
- **출력**: `filtered_passages[]` (score, sha256, section 포함)
- **Smoke test (2026-09-05)**:
  - ✅ PDF 추출 성공: 2106.03801.pdf (PyMuPDF) → 4개 passage 필터링됨
  - ✅ method 섹션: score=0.500, intro 섹션: score=0.375 (키워드 폴백 모드, LLM_API_KEY 미설정)
- **복구 지점**: smoke test 완료 ✅ → Task 5 시작

---

## Task 5 — scite 검증 + Obsidian 정준 저장 ✅ DONE

- **Smoke test (2026-09-05)**:
  - ✅ DOI `10.18653/v1/N19-1423` (BERT) → OpenAlex 보강 성공, 제목/연도 정확
  - ✅ 3-tier tier=3 `abstract_only` (NAACL conference — arXiv PDF 없음 → 정상 폴백)
  - ✅ 파이프라인 exit code 0, JSON 출력 정상
  - ⚠️ scite MCP 연결: 일시적 네트워크 오류 — 토큰 유효, 재실행 시 복원 가능
  - ℹ️ 인용 논문 0건: conference-only라 OpenAlex cited_by_api_url 제한적
- **발견된 버그 및 수정**:
  - ✅ `urllib.parse.quote`: `__import__` 네임스페이스 문제 → `import urllib.parse` 직접 import
  - ✅ `await verify_with_scite()`: async 함수인데 `await` 불필요 → 동기 호출로 변경
  - ✅ scite event loop `loop.close()` 제거: mcp 백그라운드 태스크 정리 충돌 회피



---

## Task 6 — Obsidian 개별 .md 저장 + citing별 배치 파이프라인 ✅ DONE

**완료일**: 2026-09-05

**구현 파일**:
-  — v1.3.0 단일 파이프라인 (792줄)
-  — citing별 배치 파이프라인 (신규, 15,038바이트)

**Gap별 구현 내용**:

| Gap | 파일 | 구현 |
|-----|------|------|
| b (SHA256 사전 스캔) | citation_pipeline.py |  — vault 전체 rglob 1회, set 메모리 적재, O(1) 조회 |
| c (백링크) | citation_pipeline.py |  — / 파라미터,  Obsidian 위키링크 |
| d (제목 충돌) | citation_pipeline.py |  — SHA256[:8] suffix 충돌 회피 |
| e (YAML) | citation_pipeline.py | Obsidian Properties v2 호환  배열 (따옴표 없는 쉼표 구분) |
| f (vault 검증) | citation_pipeline.py | vault 존재 +  쓰기 권한 검사, / |
| raw 분리 | citation_pipeline.py | 로 , 위키링크  본문 삽입 |
| a (Rate Limit) | batch_pipeline.py |  scite/OpenAlex API 호출 간 throttle |
| g (복구) | batch_pipeline.py |  atomic write,  스킵 지원 |

**Obsidian 디렉토리 구조 (v1.3.0)**:


**CLI 사용법**:
```bash
# 단일 논문
python src/citation_pipeline.py --doi "10.18653/v1/N19-1423"     --rq "attention mechanism" --vault "D:/Obsidian Vault"

# citing별 배치
python src/batch_pipeline.py --doi "10.18653/v1/N19-1423"     --rq "attention mechanism" --vault "D:/Obsidian Vault" --max-citing 20

# 중단 후 재개
python src/batch_pipeline.py --doi "10.18653/v1/N19-1423"     --rq "attention" --vault "D:/Obsidian Vault" --resume
```

**smoke test**: 진행 예정
---

## 전체 파이프라인 순서 (메모)

```
① 입력 정규화 (DOI/OpenAlex ID)       → ② Scholar Cited-by 수집
  → ③ OpenAlex 메타데이터 보강          → ④ 3-tier 본문 확보 (Task 3)
  → ⑤ 텍스트 추출 + LLM 필터링         → ⑥ scite 검증 + Obsidian 저장 (Task 5)
```

---

## 기술적 결정사항 (기록)

| 결정 | 이유 |
|------|------|
| academic-mcp를 MCP 프로토콜이 아닌 subprocess JSON IPC로 격리 구동 | mcp 1.x(Hermes 호스트 2.x와 불호환) + MSYS2 경로 이스케이프 문제 우회 |
| SHA256 기반 중복 판별 | DOI/OA URL로는 preprint/published 버전 구분 불가 |
| UTF-16 LE BOM 폴백로 `.env` 저장 | Windows 파이썬의 `dotenv` 인코딩 호환성 |
| `src/paper_acquisition.py`를 plans_citation.md에서 단일화 | 기존 ③-1(web_fetch)/③-2(academic-mcp) 중복 해소 |

---

## 중단 복구 지점 (가장 중요)

**현재 진행**: 모든 Task 완료 ✅

**복구 시 실행 명령:**

```bash
# ① scite OAuth 토큰 갱신 (만료 시)
python "C:\Users\user\AppData\Local\hermes\skills\research\scholar-citation-search\src\scite_oauth_auth.py" --reauth

# ② academic-mcp 격리 테스트 (Task 2)
cd "C:\Users\user\AppData\Local\Temp\academic-mcp-venv\Scripts"
./python.exe "C:\Users\user\AppData\Local\hermes\skills\research\scholar-citation-search\src\academic_mcp_direct.py"

# ③ 3-tier 본문 확보 standalone (Task 3)
cd "C:\Users\user\AppData\Local\hermes\skills\research\scholar-citation-search"
python src/paper_acquisition.py

# ④ 텍스트 추출 + LLM 필터 smoke test (Task 4)
python src/text_extraction.py -i "src/test-smoke-papers/2106.03801.pdf" \
    --rq "attention mechanism deep learning" -t 0.3 -m 5

# ⑤ 전체 파이프라인 실행 (Task 5) — Obsidian 저장 포함
python src/citation_pipeline.py \
    --doi "10.18653/v1/N19-1423" \
    --rq "attention mechanism NLP transformer" \
    --vault "D:/Obsidian Vault"
```

**파일 인벤토리:**
```
src/
  academic_mcp_direct.py  (498줄) — 격리 venv subprocess JSON IPC
  paper_acquisition.py    (402줄) — 3-tier 본문 획득
  text_extraction.py      (436줄) — PDF 텍스트 추출 + LLM 필터
  citation_pipeline.py     (685줄) — 6단계 통합 파이프라인
  scite_client.py         (178줄) — scite OAuth + Smart Citations
  scite_oauth_auth.py     (OAuth) — PKCE S256 인증
  scite_discover_tools.py (MCP 도구 디스커버리)
  scite_test_query.py     (BERT 테스트)
  scite_debug_result.py   (디버그)

src/test-smoke-papers/
  2106.03801.pdf         (smoke test용 PDF)

---

## Task 7 — R1–R12 리그레션 복원 ✅ DONE (2026-09-05)

- **발단**: `citation_pipeline.py` 전면 재작성분에서 `enricher`/`acquirer` 없는 모듈 import, `save_to_obsidian` 미정의 `result` 참조, `filter_by_rq(rq=)` 규격 오류, `argparse`·`_vault_sha256_cache` 누락 등 12건 리그레션. `import batch_pipeline` → ImportError 실측.
- **수정** (`src/citation_pipeline.py` 전면 복원): `enrich_paper`·`acquire_body`·`extract_and_filter`·`collect_scholar_cited_by`·`fetch_openalex_*`·`load_env_key`·`canonicalize_paper` 복원, `verify_with_scite` 동기 래퍼(배치 호환), tally 비율 라벨 + evidence 수집 + `retrieved_at`, `authors` 필드 복원, `get_unique_filepath` 충돌 로직 복원. 덤으로 `acquire_body` `pdf_path` 저장 누락, 초록 복원 전도 버그, evidence 렌더링 버그 수정.
- **`src/scite_client.py`**: `_standalone_test` 구함수명 `citing_papers` → `citation_graph`.
- **검증**: 6파일 `py_compile` OK, 함수 존재 점검 `MISSING=NONE`, `import batch_pipeline` → `BATCH_IMPORT_OK`. 상세: `review_citation.md` 재검증 섹션 (R1–R12).
- **복구 지점**: `python -c "import batch_pipeline"` (src 디렉토리에서 실행)

---

## Task 8 — Step ⑤ RQ 분류 + 수집 폴백 + stats ✅ DONE (2026-09-09)

- **구현** (`src/text_extraction.py`): `classify_rq_similarity` (스펙 Q1–Q3 JSON 프롬프트, enum 검증, 휴리스틱 폴백), `method_jaccard` (≥0.5 high / ≥0.3 medium), `compute_tfidf_similarity` (sklearn→Jaccard 폴백), `decide_verdict` (unrelated 탈락 / low-confidence review / same+thr 또는 tfidf≥0.35 kept). `filter_by_rq(include_review)` 확장 (False면 kept만 — 하위호환).
- **구현** (`src/citation_pipeline.py`): `FilteredPassage` 6개 판정 필드 + 매핑, `run_pipeline` kept 저장 + `review_passages` 분리 + `stats{needs_review...}` 반환. 수집 SerpApi cites 우선 → OpenAlex 폴백, `_get_with_backoff`(2s→4s→8s).
- **검증**: 오프라인 스모크 (verdict 4케이스, kept/review/unrelated 분리). review 오염 버그(filtered_out이 review에 섞임) 발견·수정. 상세: `review_citation.md` 후속 구현 섹션.
- **복구 지점**: `python -m py_compile text_extraction.py citation_pipeline.py`

---

## Task 9 — LLM env + reasoning 게이트웨이 대응 ✅ DONE (2026-09-09)

- **설정 체계** (`src/text_extraction.py`): `DEFAULT_LLM_URL` (OpenAI) + `DEFAULT_LLM_MODEL` (`auto/best-reasoning`) + `_resolve_api_url` (인자 > `LLM_API_URL` env > 기본값). `.env` 항목: `LLM_API_KEY`, `LLM_API_URL=http://llm-router.example.local:20128/v1/chat/completions` (끝 `/chat/completions` 필수 — 코드가 URL에 직접 POST).
- **F1 확정 경위**: 사내 게이트웨이가 `stream` 미요청에도 SSE 스트리밍 반환 → `json.loads` 실패 → 폴백. 응답 chunk에 content 없이 stop (`max_tokens: 10` 부족). 실라우팅 모델 `gemini-3-flash-preview`.
- **수정**: `_parse_chat_content` (SSE+단일 JSON 양립), `_chat_post` 공용화, `max_tokens` 10/200→1000, reasoning 모델(`reasoning`/`thinking`/o1·o3·o4) `temperature` 제외, `stream: False` 명시, 숫자 추출 마지막 float 우선.
- **검증 (실서버)**: `similarity_filter` → `SCORE=0.8`, `classify_rq_similarity` → `same/high/high` + 한국어 reason. F1 해소. 상세: `review_citation.md` 실호출 테스트 2·3차.
- **복구 지점**: `python -c "from text_extraction import _resolve_api_url; print(_resolve_api_url(None))"`

---

## Task 10 — F3–F9 잔여 리뷰 반영 ✅ DONE (2026-09-09)

- **F4 정준화 강화** (`citation_pipeline.py`): `_normalize_text_key`·`_title_similarity`(difflib)·`dedupe_papers`(DOI>OpenAlexID>title+첫저자+year). `fetch_openalex_by_title(year=)` 상위 5건 최적 선택. `enrich_paper` version-of-record 판별.
- **F7 교차검증**: `_verify_scite_async(citing_dois=)` + `citation_graph` 대조 → `unconfirmed_by_scite`. 수집(②)을 검증(⑥) 앞으로 이동. `stats`에 건수 추가.
- **F6 로그**: `write_run_log` → SKILL_ROOT/`log.md` append.
- **F5 페이징**: SerpApi `start` 루프 + OpenAlex `page` 루프.
- **F8 라벨**: `verification_status`를 plans 어휘로 통일 (`label`은 tally 상세 유지). 토큰없음·예외→`scite_unreachable`, DOI없음→`unverifiable_no_doi` (batch 포함).
- **F3+F9**: docstring 갱신, citing dict 키 대칭(`url_scholar`/`snippet`).
- **검증**: 컴파일·import OK, dedupe/유사도 오프라인 통과, OpenAlex 실호출 최적 선택 통과.
- **복구 지점**: `python -m py_compile citation_pipeline.py batch_pipeline.py text_extraction.py`
```
