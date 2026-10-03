# Progress — notebooklm-wiki (코드 수정 상황)

> 작성일: 2026-08-22
> 범위: 이 세션에서 수정된 스크립트 변경 사항 요약. 실행 로그는 `notebooklm-wiki.log` 에 기록.

## 1. Springer 401 Unauthorized — 근본 원인 수정

- **증상**: 유효한 `SPRINGER_API_KEY` 보유(quota 113/500)인데도 `[Springer] failed 401 (Unauthorized)`.
- **원인**: `search_springer` 가 키를 `Ocp-Apim-Subscription-Key` **헤더**로만 전송 → Open Access API 가 인식하지 못함.
- **수정** (`paper_search.py`, `paper_search_multi.py`):
  - 엔드포인트 `openaccess/search` → `openaccess/json`
  - 인증: `api_key` **쿼리 파라미터** 사용 (공식 `springernature_api_client` 기준)
  - `Ocp-Apim-Subscription-Key` 헤더 제거
- **검증**: `api_key=dummy` 호출 시 401 반환 확인 → 서버가 `api_key` 파라미터를 정상 평가함을 입증(인증 방식 정확).

## 2. Springer 401/403 graceful 처리

- `search_springer` 에 401 브랜치 추가 (Elsevier 와 동일 동작): 명확한 경고 후 `[]` 반환. 기존엔 `raise_for_status` → 예외/재시도 루프로 불명확한 에러 발생.

## 3. paper_search_multi.py Springer 파싱 드리프트 수정

- 오된 shape(`landingPageUrl`, `creators[].name`) → `paper_search.py` 실제 shape 으로 수정:
  - `url`: `[{"value": ...}]` 리스트/딕셔너리 모두 처리, 없으면 DOI 링크 fallback
  - `creators`: `[{"creator": "Name"}]` 처리
  - `abstract`: `{"p": [...]}` dict → 문자열 결합
  - `publicationDate` 필드 사용
- 단위 테스트로 `paper_search.py` 와 파싱 일치 확인.

## 4. notebooklm_wiki_sync.py (코드 리뷰 finding 기반)

- **F2** `use` 서브커맨드 → `-n` 플래그 복원. (`source list`/`fulltext`/`ask` 모두 `-n` 지원 확인 via `--help`; 전역 컨텍스트 변이 제거)
- **F1** `generate_atomic_note` 가 규칙 파일(`atomic_note_rules.md`) 부재 시 `None` 반환(런 전체 중단 제거). **원문(raw)을 먼저 저장**하고 Atomic 은 best-effort(실패해도 원문 보존, `rebuild-atomic` 로 재생성 가능).
- **F4** `source_id` 파일명 sanitize (`re.sub(r'[<>:"/\\|?*]', "_", ...)`) — `.atomic_prompt_*.txt` 및 atomic md 파일명. Windows 유효 문자 대응.
- **F8** atomic 교체 파일명 `source_id[:12]` → 전체 sanitize id (충돌 방지).
- **F3** `source_exists_in_wiki` 가 신·구 키 형식(`{nb}:{type}:{id}` / `{type}:{id}`) 모두 수용 (포맷 변경 전 상태 파일도 중복 방지, 마이그레이션 불필요).
- **F7** (daemon 알림) 합리적 판단으로 유지 / **F6** (`openaccess/json`) 이미 정확 / **F9** (PubMed 초록 미제공) known limitation — 비회귀.

## 5. 기타 (이전 세션)

- `notebooklm_wiki.py`: `run_notebooklm_command` 에 `env` 파라미터 + auth 실패 시 `auth refresh` 자동 재시도; subprocess UTF-8 인코딩(cp949 `UnicodeEncodeError` 대응).

## 실행 계획

- 키워드 `"amyloid plauqe"` 로 Springer Nature Open Access API 라이브 검색(디버깅 포함).
- 실행 로그: `notebooklm-wiki.log` (신규 파일).

## 7. Elsevier AuthenticationAPI.wadl + ScienceDirectSearchAPI.wadl 기반 수정 (2026-08-22)

- **근거**: `AuthenticationAPI.wadl` — `X-ELS-APIKey`/`apiKey`, `X-ELS-Insttoken`/`insttoken`, `Accept`/`httpAccept`; `ScienceDirectSearchAPI.wadl` — `https://api.elsevier.com/content/search/sciencedirect` (PUT native, GET legacy), `Accept: application/json` 필수, `X-ELS-APIKey` 필수, `query`(필수)/`view`(STANDARD만)/`count`(10/25/50/100)/`start`(0-6000).
- **수정** (`paper_search.py` + `paper_search_multi.py` `search_elsevier`):
  - Endpoint: `content/search`(모호)/`content/metadata/article`(단건 조회) → **`content/search/sciencedirect`** (WADL의 ScienceDirect Search V2; Scopus는 `/content/search/scopus`)
  - 인증: WADL 규격대로 **`X-ELS-APIKey` 헤더**로 통일, `apiKey`/`httpAccept` 쿼리 제거. `ELSEVIER_INST_TOKEN`→`X-ELS-Insttoken` 선택 지원.
  - 파라미터: `view=STANDARD`(WADL 유일 허용), `count`는 10/25/50/100으로 정규화(5 요청→10), `start` 문자열화.
  - 응답 파싱: ScienceDirect는 모든 entry에 `@_fa=true` — facet 스킵 제거. `authors.author[].$` + `dc:creator` fallback, `prism:coverDate` 우선으로 날짜 수정. 403 분기 추가.
- **라이브 검증** (`amyloid plaque`, `.env`의 `ELSEVIER_API_KEY`):
  - 1차(Scopus): 401 — 키 무효/기관 IP 미연동. 코드 graceful 처리 확인.
  - 2차(ScienceDirect): **`200` 10건 검색 성공** (WADL 규격 준수 후). `paper_search_multi`는 `@_fa` 스킵 버그로 0건이었으나 수정 후 양 모듈 모두 10건, `coverDate` 정상(2026-07-28 등). `count=5`→`10` 정규화 동작 확인.

## 8. 재검토(2nd review) 반영 수정 (2026-08-22)

전체 재검토 후 **High + Medium**만 수정:

- **[High] `paper_search.py` search_springer `for/else` 가드 추가** — 429 3회 연속(쿼터 소진) 시 `data` 미바인딩 `UnboundLocalError` 크래시. multi에는 있던 가드를 이쪽에도 추가. 모킹 테스트로 429×3 → 깨끗한 `[]` 반환 확인.
- **[High→완화] 핸들러 드리프트**: `paper_search_handler.py`가 `paper_search`만 import하므로, 런타임 파이프라인이 쓰는 `paper_search.py` 쪽을 직접 고치는 방식으로 해결(모듈 통합은 별도 과제).
- **[Medium] Elsevier URL/id 정렬** (`paper_search.py`): `@URL`(없는 키) dead code 제거 + `"link": []` IndexError 방지 — `@href` 안전 파싱(self ref 제외), DOI 우선(`prism:doi`), doi.org 링크 교체. multi와 동작 일치.
- **[Medium] 시크릿 유출 차단** (양 파일 springer): 제네릭 except 로그에서 URL 내 `api_key` 값을 `***` 마스킹. 테스트로 `api_key=***` 마스킹 확인(기존 로그엔 실키 노출됨 — `notebooklm-wiki.log` 삭제 여부는 사용자 결정).
- **[Medium] Semantic Scholar 날짜 버그** (양 파일): `(pub_date or str(year)) if year else ""` 우선순위 오류 / `str(None)="None"` → 각각 올바른 조건식으로 수정.
- **[Medium] Elsevier max_results 계약 복원** (양 파일): count 정규화(5→10) 후 반환 전 `papers[:max_results]` 절단 — "10건 중 5건 반환" 로그.
- **[Medium] rebuild_atomic 구키 수용** (`notebooklm_wiki_sync.py`): `{type}:{id}` 구키 기록 소스도 재생성 대상에 포함(sync_notebook의 source_exists_in_wiki와 대칭).
- **[Medium] notebooklm_wiki.py:227 local-file source add 인자 순서** — CLI 확인(`source add CONTENT -n <nb>`) 결과 notebook_id가 CONTENT 위치에 들어가던 버그 → `-n` 플래그로 수정.

**수정 안 함(판명: 정상/문서화)**: STANDARD view 초록 공백(WADL상 불가피 — docstring 명시됨), 404 fallback 로직, 500-마지막-시도 경로, PubMed 초록 공백(esummary 한계).

검증: `py_compile` ×4 통과, 모킹 스모크 테스트(429×3 가드, 시크릿 마스킹, 절단/URL/저자/날짜, 빈 link[]) 전부 통과.

## 9. 잔여 항목 전부 수정 (2026-08-24)

리뷰에서 "남긴 것"으로 분류했던 3개 항목 + 라이브 검증 중 발굴한 사일런트 버그:

- **[해결] PubMed 초록 공백 → efetch 연동**: `esummary`엔 초록이 없으므로 `_fetch_pubmed_abstracts()` 헬퍼가 `efetch.fcgi`(XML, stdlib ET)로 일괄 조회. 중첩 태그(`<b>` 등) itertext 수집 + 공백 정규화. **라이브 검증: 3건 조회 시 초록 3/3 (최대 1,897자).**
- **[근본 원인 발견·수정] PubMed가 실제론 항상 0건이었음**: `datetype=pudate`는 무효값 — NCBI가 에러 없이 count=0 반환(원시 프로브로 입증: pudate 0건 vs pdat 856건). `.bak`에도 존재한 고질 버그. → **`pdat` 로 수정.**
- **[구현·키 한계 확인→해결] Elsevier STANDARD 초록 보강**: STANDARD view엔 초록 필드가 없어 3단계 폴백 체인으로 보강(기본 ON, `ELSEVIER_SKIP_ABSTRACT_ENRICH=1` 비활성, 절단 후 보강):
  1. Abstract Retrieval `/content/abstract/pii/{pii}` view=META (무료) — 단, META엔 초록 필드 자체가 없음(FULL view는 401).
  2. Crossref DOI 폴백 — Elsevier는 초록을 대부분 deposit하지 않음(프로브: len 0).
  3. **OpenAlex 폴백** — abstract_inverted_index 재조립. **라이브 검증: Cell Reports 논문 1,102자 실초록 확보**(`raw.abstract_source="openalex"`).
  - 전문(Article Retrieval)은 TDM 동의만으로는 불가 — JSON/XML/헤더 전부 403 "Requestor configuration settings insufficient"(기관 IP 또는 Insttoken 필요). 프로브로 입증.
  - 한계: 인덱싱 직후 신규 논문은 세 API 모두 초록 부재 가능(빈값 유지, 에러 아님).
- **[완료] 모듈 통합**: `paper_search_multi.py`를 thin wrapper로 재작성 — 엔진은 `paper_search.py` 단일 모듈. 구 퍼블릭 인터페이스(Paper, search_*, search_all_repos, paper_to_dict, papers_to_display, CLI 플래그) 완전 보존 + 명시적 API 키 kwargs→env 반영. 드리프트 재발 원천 차단.
- **[보강] Retry-After 안전 파싱** (`_retry_after_seconds`): HTTP-date 등 비숫자 값 시 ValueError 대신 default 사용 — SS/Springer/Elsevier 3곳 적용.

검증: `py_compile` ×4, 모킹 스모크(wrapper identity/efetch 파싱/보강·403·kill-switch/key→env) 전부 통과, 라이브(PubMed pdat+efetch, SD 절단·보강 degrade, 통합 4건) 확인. 실행 로그는 `notebooklm-wiki.log`.

## 주의

- `.env` 에 `SPRINGER_API_KEY`, `ELSEVIER_API_KEY`, `SLACK_BOT_TOKEN` 등 **비밀키 포함** — 저장소에 커밋 금지. 본 progress.md 및 notebooklm-wiki.log 에 키 값은 기록하지 않음.
- 참고: §8 이전 실행 로그(`notebooklm-wiki.log`)에는 마스킹 전 실키가 포함된 에러 라인이 존재할 수 있음 — 배포/공유 전 해당 로그 삭제 또는 클렌징 권장.
- Elsevier 초록 보강은 현재 키의 엔타이틀먼트 부족(403)으로 항상 빈값 — 권한 확장 전까지는 정상 동작이 아닌 제한으로 문서화됨(§9).

## 6. 라이브 검색 디버깅 (2026-08-22)

- **라이브 검증 성공**: repo root `.env` 의 `SPRINGER_API_KEY` 로 실제 API 호출 → `openaccess/json` + `api_key` 쿼리 파라미터가 정확(§1 의 401 수정 확인).
  - 연결성 테스트: `api_key=dummy` → 401 반환 = 서버가 `api_key` 파라미터를 정상 평가함을 증명.
  - 키워드는 `"amyloid plaque"` → 5건 정상 결과(URL/저자/날짜/초록 모두 정상 파싱).
- **버그 발견 및 수정** (search_springer, `paper_search.py` + `paper_search_multi.py`):
  1. **404 미처리**: `keyword:` 필드 검색은 용어 미일치 시 404 를 반환하는데, 기존 코드는 `raise_for_status` → 예외 + 3회 재시도(약 12s 낭비) + scary 에러. → **수정**: 404 시 평문 쿼리(`keyword:` prefix 제거)로 1회 fallback, 그래도 없으면 빈 결과(info 로그). 사용자 입력 오타(`amyloid plauqe`)도 크래시 없이 0건 처리.
  2. **401 브랜치 누락**: 사용자의 `keyword:` 업데이트 과정에서 `paper_search.py` 의 401 브랜치가 사라짐 → **재추가** (Elsevier 와 동일 동작).
  3. **abstract 파싱 버그**: `" ".join(abstract["p"])` 가 `p` 가 문자열/문자배열일 때 글자마다 공백(`P r o p...`)을 유발. → **수정**: `p` 가 문자열이면 그대로, 리스트면 `""` join. (§3 패턴과 일관)
- **실행 로그**: `notebooklm-wiki.log` (신규) 에 기록 완료 (헤더/타임스탬프 + [Springer] INFO 로그 + 결과).
- **참고(실행 환경)**: `paper_search_multi.py` CLI 의 `load_dotenv()` 는 CWD 기준 → `scripts/` 에서 실행 시 repo root `.env` 를 못 읽음. 실제 CLI 실행은 **repo root** 에서 하거나 `SPRINGER_API_KEY` 환경변수를 직접 설정할 것. (본 디버깅은 runner 가 repo root `.env` 를 수동 로드함)
