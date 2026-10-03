# Progress — research_new (코드 수정 상황)

> 작성일: 2026-08-25
> 범위: 2026-08-25 세션에서 수행한 코드 리뷰 → 버그 수정 → notebooklm-wiki 진화형 패턴 이식 → 검증 전체 요약.
> 상세 근거는 `AGENTS.md` (Gotchas), `SKILL.md` (스펙) 참고.

## 0. 배경

3회 코드 리뷰(subagent) 결과가 수렴: 크론이 매일 3시간 타임아웃으로 실패 중.
근본 원인 2가지 — (C1) 크론 진입점 사본이 자기 자신을 무한 spawn,
(C2) 전역 편수 캡/시간 예산 부재로 88편 순차 요약(로그상 43/88에서 강제 종료, 2026-08-21).

## 1. 치명적 버그 수정

### C1. 래퍼 무한 재귀 (`run_pipeline.py`)
- `subprocess.call([VENV_PYTHON, os.path.join(SCRIPT_DIR, "research_pipeline.py")])` 구조상,
  래퍼가 다른 폴더(`hermes\scripts\`)로 복사되면 자기 자신을 영원히 spawn.
- **수정**: 실제 오케스트레이터를 절대 경로로 지정하는 위임 래퍼로 재작성 + CLI 인자 전달 추가.
- **외부 사본 교체**: 크론이 실제로 실행하던 `hermes\scripts\research_pipeline.py`(794B 구형 래퍼 사본)도 동일 내용으로 교체.

### C2. 시간 예산 부재 (`research_pipeline.py`)
- 신규 환경변수: `RESEARCH_MAX_TOTAL_PAPERS`(기본 12, dedup 후 절단),
  `RESEARCH_TIME_BUDGET_SECS`(기본 7200, 초과 시 남은 논문은 "[시간 예산 초과로 요약 생략]" 표기 후 Slack 전송 → 부분 결과 보존).
- LLM 요청 하드코딩 `timeout=2400s × 3` → `LLM_TIMEOUT_SECS`(기본 600)/`LLM_MAX_RETRIES`(기본 3) 환경변수화.
- 로그 `FileHandler` → `RotatingFileHandler`(5MB×3).

## 2. paper_search.py 안정화

- **Springer**: 재시도 루프에 `for-else` 누락 → 429 연속 시 `NameError` (`data` 미할당). 수정 완료.
- **Elsevier**: 에러 엔트리 필터가 `@_fa == "true"` 조건 — 정상 엔트리에도 존재하는 속성이라 모든 엔트리 드랍 위험. `"error" in entry`로 수정.
- **Retry-After**: HTTP-date 포맷 헤더 → `int()` ValueError. `_retry_after()` 안전 파싱 도입(SS/Springer/Elsevier 공통).
- **bioRxiv 페이징**: `page_size = max_results*20`(500) + `cursor < 200` 결합으로 실질 1페이지만 스캔. `page_size=100 × 최대 3페이지`로 재작성, 죽은 `base_url` 제거.
- **search_all**: 키워드 `&`→공백 정화(모든 소스), 소스별 try/except 격리(한 소스 예외가 타 소스 결과를 폐기하지 않음), dedup set 기반 O(n) + 영숫자 정규화.

## 3. local_llm_summarize.py

- `_extract_content`: `choices` 빈 배열 `IndexError` 가드.
- 모델 캐시: URL별 분리 캐시 + 조회 실패는 미캐시(다음 호출 재시도). Vision이 텍스트 LLM(GLM-5.2) 모델명을 Qwen 서버에 보내던 버그 수정 → `get_model(VISION_LLM_URL)`.
- 로컬 이미지 data-URL을 스펙형 `{type: image_url, image_url:{url}}`로 래핑.
- PDF 임시파일 `finally` 삭제 + 50MB 상한 + stream 다운로드.
- PDF 폴백 활성화: bioRxiv DOI→`.full.pdf` 직접 구성 (구 `endswith(".pdf")` 데드코드 제거).

## 4. slack_research_notifier.py

- 번호목록 판별 `startswith("1")` → 정규식 `^\d+\s*[.)]` ("1,25-dihydroxy…" 본문 오검출 방지).
- `import time` 함수 내 중복 → 모듈 상단. Slack 토큰 호출 시점 재조회(lazy).

## 5. notebooklm-wiki 진화형 패턴 이식 (2026-08-25 2차)

`../notebooklm-wiki/scripts/paper_search.py`의 성숙한 구현을 이식. 다중키워드/소스 격리/전역 캡은 research_new 고유 기능으로 유지.

- **Elsevier 엔드포인트 전환**: `/content/metadata/article`+COMPLETE(키 유효해도 401 확인됨) → **ScienceDirect Search API V2** `/content/search/sciencedirect`, `view=STANDARD`, `X-ELS-APIKey` 헤더(+선택 `ELSEVIER_INST_TOKEN`), count 정규화(10/25/50/100), link `@href` 안전 파싱, 저자 이중 포맷, DOI 링크. **라이브 검증: 401 → 1건 반환.**
- **초록 보강 체인**: Abstract Retrieval(META, PII) → Crossref(DOI) → OpenAlex(DOI). `ELSEVIER_SKIP_ABSTRACT_ENRICH=1`로 비활성. 검증: DOI당 ~1086자 회수.
- **PubMed**: `datetype=pudate→pdat` (라이브 검색 0건→2건 복활), efetch `itertext()` 중첩태그/공백 정규화.
- **Springer**: 404 시 평문 쿼리 1회 재시도 폴백, 401 graceful 처리, 에러 로그 API 키 마스킹, abstract `p` str/list 이중 파싱.
- **bioRxiv**: URL 미존재/비http 시 ID로 재구성 폴백.
- **cp949 콘솔**: `sys.stdout.reconfigure(encoding="utf-8")` (pipeline + CLI) — 한글/이모지 깨짐 해소.

## 6. 보안/운영

- `.env.example`의 실제 API 키·Slack 토큰 → placeholder 교체. **유출된 값 로테이션 권장** (Elsevier 키는 401 무효 확인).
- `.gitignore` 신설 (`.env`, `__pycache__/`, `*.log`). git 미초기화 저장소.
- AGENTS.md 신설·갱신 (실행 명령, .env 함정표, 아키텍처, 코드 검증 Gotchas).
- **venv 사고(2026-08-25)**: hermes 업데이트 인터럽트로 `hermes-agent\venv` 소실 → 사용자 복구. 복구본에 `slack-sdk`, `pymupdf` 누락되어 재설치 완료. 향후 venv 재생성 시 두 패키지 필요.

## 7. 검증 요약 (2026-08-25)

| 항목 | 결과 |
|------|------|
| py_compile / 임포트 (5개 스크립트) | OK (hermes venv 3.11.9) |
| 단위: Retry-After/dedup/_extract_content/불릿정규식/파이프라인 시그니처 | 통과 |
| 실검색 `tauopathy` (max=2, lookback=1) | PubMed 2 + Springer 2 + Elsevier 1 = 5건 (SS 429 안전 스킵) |
| 초록 보강 | Crossref/OpenAlex 각 1086자 회수 |
| E2E 스텁 (Slack/LLM mock) | 캡 5→3 적용, 메시지 빌드, 청킹 통과 |

## 8. Slack/LLM 출력 포맷 변경 (2026-08-25 후속)

- **논문당 출력 4항목으로 축소**: 제목 / 링크 / 목적 / 결과 요약. 기존의 `PMID:xxx |` ID 프리픽스, 핵심·방법 다중 불릿, 이미지 설명 라인 제거.
- **프롬프트 안내문 누출 차단**:
  - 시스템 프롬프트를 "목적:/결과: 정확히 두 줄만 출력" 형식 강제로 교체 (기존 "3-5 concise bullet points" 스타일은 GLM-5.2가 지시문을 그대로 에코하는 원인).
  - `_clean_llm_text()` 후처리 클리너 추가 — 코드펜스 제거, 영어 안내문 라인("The user wants...", "summary needs to be..." 등) 정규식 제거, 마크다운 강조(`**목적:**`) 정규화. `summarize_abstract` 반환 경로에 적용.
- **렌더링 파서**: `_parse_summary()`가 `목적:`/`결과:`(영어 라벨 포함) 행을 인출해 각 한 줄로 표시. 라벨 파싱 실패 시 요약 앞 2줄 폴백 → `[요약 실패]`/`[시간 예산 초과로 요약 생략]` 플레이스홀더도 계속 표시됨.

## 9. 요약 스타일 개편 (2026-08-25 후속 2)

- **출력 4항목 확정**: 제목 / 링크 / 목적 / 결과 요약 (§8 연장).
- **결과 길이 제한 해제**: `결과:` 행 truncate 300→2000자, 프롬프트에서도 "길이 제한 없음" 명시.
- **Graphical Abstract 완전 제거**: `summarize_image()`, `find_graphical_abstract_url()`, `VISION_SYSTEM_PROMPT` 삭제. 사용자가 줄인 `SummaryResult`/`PaperWithSummary`와 정합화 — `_placeholder_paper`가 제거된 필드(`graphical_abstract`/`image_summary`)를 전달하던 TypeError 예정 크래시 수정. 미사용 `base64`/`Optional` import 정리.
- **두 모드 도입** (`summarize_abstract(mode=)`):
  - **fulltext 모드**: PDF 전문(최대 8페이지, 기존 3→8) + `_extract_figure_captions()`로 감지한 Figure 캡션 목록을 함께 전달 → 본문 흐름/Figure 순서대로 서술 유도. bioRxiv DOI·SS openAccessPdf 경로.
  - **abstract 모드**: 초록을 논리 전개에 맞춰 정리하되 불완전 부분 추론 보완 허용.
- **`(추론)` 마커**: 근거 없는 해석은 문장 끝 `(추론)` 표기 — 두 모드 프롬프트 공통 규칙.

## 10. 선발 로직 개편: IF 우선 + 키워드 배분 (2026-08-26)

**문제**: 구 절단(`papers[:12]`)은 삽입 순서 그대로 → 첫 키워드의 Springer/Elsevier 상위 12건만 남고 나머지 키워드는 대표성 없음 (08-26 05:00 런에서 실제 발생).

**새 선발 계층** (`paper_search.search_all(per_keyword=)`):
- **저널 Impact Factor 우선**: `_IMPACT_FACTOR` 테이블(주요 생명과학 저널 ~40종 근사 IF) 기반 `_impact_score()`. 미지정 저널 8.0 / 프리프린트 5.0, 인용수 보정(+1/100회, 최대 +10 — SS `citationCount` 필드 신규 수집).
- **키워드당 N건** (`RESEARCH_MAX_PAPERS_PER_KEYWORD`, 기본 5): 각 키워드 버킷에서 IF 순 상위 N건 직접 선발.
- **부족분 재배분**: 검색 실패/미달 키워드의 몫(per_keyword × 총 키워드수까지)은 잔여 풀에서 IF 순으로 채움.
- 파이프라인은 `RESEARCH_MAX_TOTAL_PAPERS`(기본 30)를 안전망으로만 유지, 시간예산이 1차 방어.

**검증**: 단위(점수 순서/배분·재배분/per-keyword 캡) + 통합 스텁(kw1=8건, kw2=2건, kw3=0건 → Nature 논문 1위, kw1 5+재배분3, kw2 2, 총 10건=풀 고갈) 통과.

## 남은 과제

- [ ] Springer/Elsevier API 키 및 SLACK_BOT_TOKEN 로테이션
- [ ] SS 429 만성 — 무료티어 한계. API key 확보 또는 키워드 간 sleep 도입 검토
- [x] ~~Vision 경로~~ → §9에서 완전 제거 (2026-08-25)
- [ ] RESEARCH_MAX_RESULTS=25 → SKILL.md 권장 3~5로 낮추는 것 검토 (전역 캡이 있어 필수는 아님)
