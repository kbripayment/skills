# research_new 파이프라인 검토 및 오류 분석 보고서 (`review_research_new.md`)

## 1. 개요 및 긴급 오류 분석

### 1.1 발생 오류 요약
- **증상**: 스크립트 실행 즉시 종료 (Exit Code 1)
- **오류 메시지**:
  ```text
  Traceback (most recent call last):
    File "C:\Users\user\AppData\local\hermes\skills\research\research_new\scripts\research_pipeline.py", line 274, in <module>
      f"MaxResults: {MAX_RESULTS}, PerKeyword: {MAX_PER_KEYWORD}, TotalGuard: {MAX_TOTAL_PAPERS}, TimeBudget: {TIME_BUDGET_SECS}s")
                                                                                                               ^^^^^^^^^^^^^^^^
  NameError: name 'TIME_BUDGET_SECS' is not defined
  ```

### 1.2 근본 원인 (Root Cause)
1. **변수 선언과 참조의 불일치**:
   - `scripts/research_pipeline.py` 상단 설정부(96~98행)에서 마감시간 변수가 `GLOBAL_DEADLINE_SECS`로 리팩토링 및 선언되었으나, 스크립트 최하단 `if __name__ == "__main__":` 블록(274행)의 시작 로그 포맷 스트링에는 구 변수명인 `{TIME_BUDGET_SECS}s`가 그대로 남아 있었습니다.
   - 이로 인해 `run_pipeline()` 함수가 호출되기도 전인 스크립트 초기화 단계에서 `NameError`가 발생해 파이프라인이 즉각 중단되었습니다.

2. **환경변수 명칭 및 문서 불일치**:
   - `SKILL.md`(57, 265, 308행), `.env.example`(18행), `progress.md`(23행) 등 공식 사양서에는 환경변수명이 `RESEARCH_TIME_BUDGET_SECS`(기본값 7200초)로 정의되어 있습니다.
   - 반면 `research_pipeline.py` 코드에서는 `_env_int("RESEARCH_GLOBAL_DEADLINE_SECS", 3600)`로만 읽고 있어, 사용자가 `.env`에 `RESEARCH_TIME_BUDGET_SECS`를 설정하더라도 무시되는 설정 단절이 존재했습니다.

---

## 2. `scripts/research_pipeline.py` 중심 심층 코드 리뷰

### 2.1 주요 검토 영역 및 분석

| 영역 | 기존 코드 상태 | 문제점 및 취약점 | 권장 개선 방향 |
|---|---|---|---|
| **시간 예산 설정** | `GLOBAL_DEADLINE_SECS`만 정의, `TIME_BUDGET_SECS` 미정의 | 스크립트 시작 시 `NameError` 발생, `RESEARCH_TIME_BUDGET_SECS` 환경변수 무시 | `RESEARCH_TIME_BUDGET_SECS`와 `RESEARCH_GLOBAL_DEADLINE_SECS`를 상호 폴백 지원하고 `TIME_BUDGET_SECS = GLOBAL_DEADLINE_SECS`로 일치화 |
| **타임존 / 날짜 표기** | `now = datetime.now(timezone.utc)` 후 `date_str = now.strftime("%m/%d")` | 로그에는 `KST-{lookback_days}일`로 표기하나, 새벽 5시 KST 실행 시 UTC는 전날 오후 8시이므로 Slack 메시지 헤더 날짜가 전날(어제)로 찍힘 | `timezone(timedelta(hours=9))`를 적용하여 KST 기준 정확한 당일 날짜 추출 |
| **CLI 인자 파싱** | `arg_days = int(sys.argv[2])` 직접 형변환 | 잘못된 인자(공백, 문자열 등) 입력 시 `ValueError`로 즉각 크래시 | `try-except ValueError`로 감싸고 경고 후 기본값(`LOOKBACK_DAYS`) 유지 |
| **최상위 예외 처리** | `__main__` 레벨에 `try-except` 없음 | `run_pipeline()` 진입 전/후 예외 발생 시 Slack 에러 알림(`send_error_to_slack`)이 누락되어 조용히 실패 | `__main__` 블록 전체를 `try-except`로 보호하여 치명적 초기화 오류도 Slack 통보 |
| **서킷 브레이커 로직** | 연속 2회 / 누적 4회 실패 시 발동 | 발동 이후 남은 모든 논문에 대해 루프 돌 때마다 `logger.warning`이 중복 출력됨 | 상태 기반 전환은 정확하나 로깅 노이즈 최소화 고려 |
| **로깅 핸들러** | `RotatingFileHandler(5MB, backupCount=3)` | 정상 작동. 과거 단일 append-only 이슈 해결됨 확인 | 유지 |

### 2.2 파이프라인 2단계 방어 체계 분석
`research_pipeline.py`는 과거 크론 타임아웃(3시간) 문제를 방지하기 위해 정교한 2단계 방어 메커니즘을 갖추고 있습니다:
1. **검색 단계 타임아웃 (`SEARCH_TIMEOUT_SECS = 600s`)**:
   - `search_all(..., deadline=search_deadline)`을 통해 5개 출처 검색이 10분을 넘지 않도록 차단.
2. **요약 단계 글로벌 데드라인 & 슬랙 안전 버퍼 (`SLACK_BUFFER_SECS = 180s`)**:
   - `remaining < SLACK_BUFFER_SECS` 진입 시 남은 논문은 LLM 요약을 즉시 생략하고 `_placeholder_paper`(원문 초록 최대 600자)로 대체하여 Slack 발송을 보장.
3. **서킷 브레이커 (연속 2회 / 누적 4회 LLM 실패)**:
   - 로컬 LLM 서버(llm-chat.example.local) 장애나 과부하 발생 시 더 이상 대기하지 않고 즉시 원문 초록으로 대체 전송.

---

## 3. 연계 모듈 및 시스템 상태 점검

### 3.1 `scripts/paper_search.py`
- **5-Source 통합 검색**: PubMed, bioRxiv, Semantic Scholar, Springer Nature, Elsevier 정상 지원.
- **키워드 선발 로직**: 저널 Impact Factor 가중치(`_IMPACT_FACTOR`) + 인용수 보너스를 적용해 키워드별 상위 N건 선발 후 잔여 풀 재배분 정상 동작.
- **예외 격리**: 소스별 `try-except`로 개별 API 장애(예: Semantic Scholar 429, Springer 401/403)가 타 소스 수집을 방해하지 않음.
- **과거 AGENTS.md 이슈 점검**:
  - `Springer retry missing for-else`: `else:` 블록이 이미 추가되어 정상 방어됨.
  - `Elsevier for-else dead code`: ConnectionError 시에도 재시도 카운트를 거치도록 수정 완료됨.
  - `bioRxiv OR 매칭`: `and_blocks` 및 단어 경계(`\b`) 정규식 매칭이 적용되어 오탐 방지됨.

### 3.2 `scripts/local_llm_summarize.py`
- **모드 분기**: Fulltext(PDF 본문 발췌 + Figure 캡션) 우선, 초록(Abstract) 폴백 지원.
- **타임아웃 정책**: `LLM_TIMEOUT_SECS = 240s`, `LLM_MAX_RETRIES = 1`로 CPU 기반 GLM-5.2 환경에서 지연 최소화.
- **보안**: SSRF 방어 필터(`_is_safe_url`)를 통해 비학술 도메인 및 사설 IP 대역 PDF 접근 차단.

### 3.3 `scripts/slack_research_notifier.py`
- **메시지 분할**: Slack 메시지 길이 상한(3000자) 대응 청크 분할(`send_to_slack`) 정상 지원.
- **에러 알림**: `send_error_to_slack` 정상 구비.

### 3.4 래퍼 스크립트 (`run_pipeline.py`, `run_pipeline.bat`)
- `run_pipeline.py`: 절대경로 위임 방식이 적용되어 과거 재귀 호출 버그 방지 완료.
- `run_pipeline.bat`: CLI 인자(`%*`)가 누락되어 있었으나, 파라미터 전달이 가능하도록 `%*` 추가 보강 완료.

---

## 4. 조치 및 코드 수정 내역 (Applied Changes)

### 4.1 `scripts/research_pipeline.py` 수정
1. **`TIME_BUDGET_SECS` 정의 및 환경변수 호환성 보장**:
   ```python
   # SKILL.md 및 하위 호환을 위해 RESEARCH_TIME_BUDGET_SECS와 RESEARCH_GLOBAL_DEADLINE_SECS 모두 지원
   TIME_BUDGET_SECS = _env_int(
       "RESEARCH_TIME_BUDGET_SECS",
       _env_int("RESEARCH_GLOBAL_DEADLINE_SECS", 3600)
   )
   GLOBAL_DEADLINE_SECS = TIME_BUDGET_SECS
   ```
2. **KST 타임존 적용**:
   ```python
   from datetime import datetime, timezone, timedelta

   kst = timezone(timedelta(hours=9))
   now = datetime.now(kst)
   date_str = now.strftime("%m/%d")
   logger.info(f"=== Research Pipeline 시작: {topic} (KST-{lookback_days}일)")
   ```
3. **`__main__` 블록 견고화**:
   - `arg_days` 파싱 시 `ValueError` 안전 처리.
   - 최상위 블록 전체를 `try-except`로 래핑하여 초기화 실패 시에도 `send_error_to_slack` 호출.

### 4.2 `scripts/run_pipeline.bat` 수정
- Python 실행 커맨드라인 뒤에 `%*`를 추가하여 배치 파일로 전달된 인자가 `research_pipeline.py`로 온전히 전달되도록 수정.

---

## 5. 검증 및 테스트 결과

1. **바이트코드 컴파일 검증 (`py_compile`)**:
   - `python -m py_compile scripts/research_pipeline.py` 실행 완료: **Syntax OK (종료 코드 0)**.
2. **변수 정의 및 로딩 검증**:
   - `TIME_BUDGET_SECS` 및 `GLOBAL_DEADLINE_SECS` 정상 로드 확인 (`3600s`).
   - 환경변수 `RESEARCH_TIME_BUDGET_SECS=7200` 주입 테스트 시 정상 오버라이드 확인 (`7200s`).
3. **초기화 진입 테스트**:
   - `NameError`가 완전히 해소되어 스크립트 실행 시 정상적으로 파이프라인 진입 로그 출력 확인.

---

## 6. 결론 및 향후 권장사항

1. **즉각적 조치 완료**: `TIME_BUDGET_SECS is not defined` 에러는 `research_pipeline.py` 내 변수 선언 및 상호 호환 처리를 통해 완벽히 해결되었습니다.
2. **문서 동기화 권장**: `SKILL.md` 및 `.env.example`에 기재된 `RESEARCH_TIME_BUDGET_SECS`와 `RESEARCH_GLOBAL_DEADLINE_SECS`가 동일하게 동작하도록 양방향 지원되므로, 운영 환경의 `.env` 수정 없이 즉시 정상 구동됩니다.
3. **모니터링**: Hermes Cron(`0 5 * * *` KST) 실행 시 Slack 채널로 정상 보고서가 전송되는지 확인하십시오.
