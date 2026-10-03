---
name: research_new
description: "매일 새벽 5시 KST, 설정한 주제로 PubMed/bioRxiv/Semantic Scholar/Springer 검색 → Local LLM 요약 → Slack 알림 자동화."
version: 1.1.0
author: Hermes Agent
license: MIT
category: research
tags: [Research, Automation, Cron, Slack, Local-LLM, Paper-Search]
related_skills: [arxiv, paper-summary, slack-content-sharing, hermes-agent]
platforms: [linux, macos, windows]
required_environment_variables: [SLACK_BOT_TOKEN, SLACK_CHANNEL]
---

# Research New — 자동화된 일일 논문 리서치 봇

**Trigger:** 매일 새벽 5시 KST, 사용자가 설정한 연구 주제로 PubMed / bioRxiv / Semantic Scholar / Springer Nature / Elsevier (ScienceDirect Metadata API)에서 최신 논문을 검색하고, Local LLM으로 핵심 요약을 생성한 뒤 Slack 채널로 전송해야 할 때.

**Core:** 5개 출처 통합 검색 → Local LLM 요약 (fulltext 우선 / abstract 폴백) → Slack 알림

- **fulltext 모드**: PDF 전문 접근 가능(bioRxiv DOI·SS openAccessPdf) 시 전체 Figure 캡션 + 서론/고찰·결론 발췌(Head+Tail)를 함께 전달 → 본문 흐름과 Figure 순서를 따라 완성도 높은 요약 생성 (결론 누락 방지)
- **abstract 모드**: 초록만 있을 때 논리적 전개로 정리, 불완전한 부분은 추론 보완 허용 — 추론 내용은 `(추론)` 표기
- Graphical Abstract / Vision LLM 경로는 제거됨 (`VISION_LLM_URL`은 예약값)

---

## 1. 아키텍처

```\n[Cron 05:00] ──▶ [research_pipeline.py]
                          │
         ┌────────┬──────┼──────┬─────────┐
         ▼        ▼      ▼      ▼         ▼
   PubMed API  bioRxiv   SS API  Springer  Elsevier
         │        │      │       │        │
         └────────┴──────┼──────┴─────────┘
                        ▼
              [오늘 업로드된 논문 필터]
                        │
         ┌──────────────┼──────────────┐
         │              │              │
   Local LLM (텍스트 요약)  (fallback)
                        │
                        ▼
                  Slack 채널 전송
```

---

## 2. 설정 (`.env`)

| 변수 | 설명 | 예시 |
|------|------|------|
| `RESEARCH_TOPIC` | 검색 키워드 (`;`/`,` 다중 지원) | `Cancer Immunotherapy` |
| `RESEARCH_MAX_RESULTS` | **소스×키워드별 후보 수집 단위값** (최종 편수가 아님) | `25` |
| `RESEARCH_LOOKBACK_DAYS` | 발표일 기준 조회 일수 (PubMed/bioRxiv만 적용) | `1` |
| `RESEARCH_MAX_PAPERS_PER_KEYWORD` | **키워드당 최종 선발 편수** (기본 5) — 저널 IF 우선 | `5` |
| `RESEARCH_MAX_TOTAL_PAPERS` | 안전망 절대 상한 (기본 30) | `30` |
| `RESEARCH_TIME_BUDGET_SECS` | 요약 단계 시간 예산 초 (기본 7200) | `7200` |
| `SLACK_BOT_TOKEN` | Slack 봇 토큰 (`xoxb-...`) | - |
| `SLACK_CHANNEL` | 채널/DM ID (`#이름` 아님) | `D0AMMSX1NQ2` |
| `LOCAL_LLM_URL` | Local LLM 엔드포인트 (GLM-5.2) | `http://llm-chat.example.local:8888` |
| `VISION_LLM_URL` | Vision LLM 엔드포인트 (Qwen2.5-VL-72B) | `http://llm-vision.example.local:8888` |
| `LLM_MODEL` | 사용할 모델명 (빈 값 = 자동 선택) | `` |
| `LLM_TIMEOUT_SECS` | LLM 요청 타임아웃 초 (기본 600) | `600` |
| `LLM_MAX_RETRIES` | LLM 재시도 횟수 (기본 3) | `3` |
| `SPRINGER_API_KEY` | Springer Nature Open Access API 키 | `your_api_key_here` |
| `ELSEVIER_API_KEY` | Elsevier ScienceDirect Search API V2 키 | `your_api_key_here` |
| `ELSEVIER_INST_TOKEN` | 기관 토큰 (선택, 원격/프록시 접근 시) | - |
| `ELSEVIER_SKIP_ABSTRACT_ENRICH` | 초록 보강 비활성화 (`1`) | `` |

### `.env` 예시 (`.env.example` 복사 후 수정)

```ini
RESEARCH_TOPIC=Cancer Immunotherapy
RESEARCH_MAX_RESULTS=3
RESEARCH_LOOKBACK_DAYS=1
LOCAL_LLM_URL=http://llm-chat.example.local:8888
VISION_LLM_URL=http://llm-vision.example.local:8888
LLM_MODEL=            # 빈 값 = Ollama 자동 모델 선택 (권장)
SPRINGER_API_KEY=your_springer_api_key_here
ELSEVIER_API_KEY=your_elsevier_api_key_here
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token-here
SLACK_CHANNEL=C0XXXXXXXXXX
SLACK_BOT_NAME=Research Bot
```

---

## 3. 스크립트

| 파일 | 용도 |
|------|------|
| `scripts/paper_search.py` | PubMed + bioRxiv + Semantic Scholar + Springer Nature + Elsevier 통합 검색, 날짜 범위 필터링 (OR 키워드 매칭) |
| `scripts/local_llm_summarize.py` | Local LLM / Vision LLM 호출로 논문 초록 요약 (bullet point) |
| `scripts/slack_research_notifier.py` | Slack 채널에 포맷팅된 메시지 전송 |
| `scripts/research_pipeline.py` | 전체 파이프라인 오케스트레이션 (cron 진입점) |
| `scripts/run_pipeline.bat` / `run_pipeline.py` | Windows 실행 래퍼 — **절대경로 위임 방식**. 이 파일을 다른 위치로 복사해도 자기 재실행되지 않음 (과거 hermes/scripts 사본 무한재귀 사고 대응). 직접 실행은 `research_pipeline.py` 권장 |

---

## 4. 사용법

### 4.1 Cronjob (매일 05:00 KST)

```text
Job ID: a408cad4c3f1
Name: research_new_daily
Schedule: 0 5 * * *  (매일 새벽 5시 KST)
Script: research_pipeline.py  (workdir: C:\Users\user\AppData\Local\hermes\skills\research\research_new)
Status: enabled, no_agent 모드 (스크립트 stdout만 실행)
```

### 4.2 수동 실행

```bash
cd C:\Users\user\AppData\Local\hermes\skills\research\research_new
"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" scripts/research_pipeline.py
```

### 4.3 주제 변경

`.env` 파일의 `RESEARCH_TOPIC` 값을 수정하거나:
```bash
hermes config set RESEARCH_TOPIC "New Research Topic"
```

#### 4.3.1 다중 키워드 검색

`RESEARCH_TOPIC`에 세미콜론(`;`)이나 쉼표(`,`)로 구분하여 여러 키워드를 설정할 수 있습니다:
```ini
# 세미콜론 구분
RESEARCH_TOPIC=Cancer Immunotherapy; Tumor Microenvironment

# 쉼표 구분
RESEARCH_TOPIC=Cancer Immunotherapy, Tumor Microenvironment
```

각 키워드로 개별 검색 후 결과를 병합 + 중복 제거하여 Slack에 전송합니다.

---

## 5. Local LLM API (Ollama 호환)

### 5.1 텍스트 요약 — 두 가지 모드 (모델명 생략 = 자동 선택)

**abstract 모드** (초록만 있을 때):
```bash
curl -X POST http://llm-chat.example.local:8888/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "Analyze the paper ABSTRACT and output EXACTLY two lines in Korean. 목적: <연구 목적> / 결과: <주요 결과·시사점, 길이 제한 없음>. 불완전한 부분은 추론 보완 가능하며 (추론)이라고 명시. 지시문·안내문 출력 금지."},
      {"role": "user", "content": "ABSTRACT: <초록 텍스트>"}
    ],
    "max_tokens": 1024,
    "temperature": 0.3
  }'
```

**fulltext 모드** (PDF 전문 접근 시): 위와 동일하되 system에 본문 흐름 + Figure 순서 언급 규칙을 추가하고, user에 원문 초록 + 전체 논문 감지 Figure 캡션 + 본문 발췌(서론 및 고찰/결론) 목록을 전달.

### 5.2 Vision 요약 — 제거됨

Graphical Abstract / Vision LLM(Qwen2.5-VL) 이미지 요약 경로는 제거되었습니다.
`VISION_LLM_URL`은 예약값이며 현재 사용하지 않습니다.

---

## 6. Slack 메시지 포맷

논문당 **4항목만** 출력: 제목 / 링크 / 목적 / 결과 요약. (ID 프리픽스, 방법론, 이미지 설명 등은 생략)

```
🌙 [08/19] Cancer Immunotherapy; Tumor Microenvironment — 5건 발견

📄 PubMed (1건)

• Combination PD-1 blockade in melanoma
  • 목적: 멜라노마에서 PD-1 차단 병용요법의 항종양 효과를 평가함.
  • 결과: 병용군에서 종양 성장이 유의하게 억제되고 생존율이 개선됨.

  🔗 https://pubmed.ncbi.nlm.nih.gov/38290123/

📄 bioRxiv (2건)

• KCNQ2/3 regulates efferent mediated...
  • 목적: ...
  • 결과: ...

  🔗 https://www.biorxiv.org/content/...

---
Sent by Research Bot | 자동 리서치 봇
```

LLM 요약은 `목적:` / `결과:` 두 줄만 생성하도록 프롬프트가 강제되며, 응답에 지시문·안내문(예: "The user wants a summary...")이 새어 나오거나 GLM-5.2가 사고과정을 통째로 출력해도 `_clean_llm_text()` 후처리로 최종 쌍만 남깁니다. 라벨 파싱 실패 시 요약 앞 2줄을 그대로 표시하는 폴백이 있습니다. 결과 행은 길이 제한이 없으며(fulltext 모드는 Figure 흐름 서술 포함), LLM 추론 부분은 `(추론)` 마커로 구분됩니다.

---

## 7. Pitfalls

### 7.1 PubMed "today" 필터링

PubMed `esearch`는 `reldate=lookback_days` + `datetype=pdat`(발행일)로 어제/오늘 발행물 필터링. UTC 기준이므로 KST 어제 발간물도 포함될 수 있음. 초록은 `esummary`에 없으므로 `efetch`(XML, `itertext()`로 중첩 태그 수집)로 일괄 조회. 미세조정 필요 시 `mindate`/`maxdate` 사용.

### 7.2 bioRxiv 키워드 필터링

bioRxiv은 키워드 검색 API를 지원하지 않습니다. 날짜 범위 내 모든 논문을 가져온 후 클라이언트 측에서 초록/제목에 검색어가 포함되는지 **OR 매칭**으로 필터링합니다. `RESEARCH_LOOKBACK_DAYS=7` 권장 (최근 7일간 검색어 매칭 논문이 적을 수 있음).

### 7.3 Semantic Scholar Rate Limit (429)

무료 API는 1req/s 제한. 429 응답 시 `Retry-After` 헤더 기반 재시도 (최대 3회, 점진적 백오프). 500 에러도 동일하게 재시도.

### 7.4 Springer Nature Open Access API 제한

- **API**: `https://api.springernature.com/openaccess/json`
- **인증**: `api_key`를 **쿼리 파라미터**로 전달 (헤더가 아님)
- **쿼리 형식**: `q=keyword:<검색어>` (예: `q=keyword%3A%20test`)
- **Daily Quota**: 500 Hits/Day (API key당 24시간 기준)
- **Throttling**: 100 Hits/Min (분당 최대 요청 수)
- **응답 파싱**:
  - `url` 필드가 `[{"value": "..."}]` 형태 → 첫 항목의 `value` 추출
  - `abstract` 필드가 `{"h1": "Abstract", "p": [...]}` 형태 → `p` 배열을 공백으로 결합
  - `creators` 필드가 `[{"creator": "Name"}]` 형태 → 각 항목의 `creator` 값 추출
- **키워드 내 `&` 처리**: 키워드에 `&`가 들어가면(예: `autism&macrophage`) URL 파싱이 깨져 404가 발생할 수 있으므로 코드에서 자동 치환(`&` → 공백)함 (`search_all`에서 모든 소스 공통 적용)
- **404 응답**: `keyword:` 필드 검색은 용어 미일치 시 404 반환 → 자동으로 평문 쿼리 1회 재시도 후 빈 결과 처리
- **401/403 응답**: key 무효 또는 일일 할당량 초과 — 경고 후 해당 소스만 건너뜀
- API key가 없으면 Springer 검색은 자동으로 건너뜁니다 (warning 로그만 출력).
- API key는 `SPRINGER_API_KEY` 환경 변수 또는 `.env`에서 설정.

### 7.5 Elsevier API (ScienceDirect Search API V2)

- **API**: `https://api.elsevier.com/content/search/sciencedirect`
  - 구 `/content/metadata/article` + `view=COMPLETE`는 엔타이틀먼트 부족 시 401/빈 결과 반환 확인 (2026-08-25). 더 이상 사용하지 않음.
- **인증**: `X-ELS-APIKey` **헤더**로 전달, 선택 `X-ELS-Insttoken` 헤더 (`ELSEVIER_INST_TOKEN`)
- **View**: STANDARD만 허용(WADL 기준) — STANDARD엔 초록 필드가 없으므로 자동 보강:
  Abstract Retrieval(META, PII) → Crossref(DOI) → OpenAlex(DOI). `ELSEVIER_SKIP_ABSTRACT_ENRICH=1`로 비활성.
- **count**: 허용값 10/25/50/100 — 그 외 값은 최소 허용값으로 올려 요청 후 `max_results`로 절단
- **Throttling**: 100 Hits/Min (분당 최대 요청 수)
- **401** = key 무효, **403** = 권한/구독 문제(기관 IP/Insttoken 필요할 수 있음) — 경고 후 해당 소스만 건너뜀
- API key가 없으면 Elsevier 검색은 자동으로 건너뜁니다 (warning 로그만 출력).
- 200 OK이지만 검색 결과가 0건일 수 있음 — 쿼리 관련성에 따라 다름 (`tauopathy` 등 특정 쿼리는 0건 가능).

### 7.6 Local LLM 모델 선택

GLM-5.2 (llm-chat.example.local:8888)는 `model` 파라미터를 생략하면 자동으로 모델을 선택합니다.
model을 명시하면 해당 모델을 로드하려 하지만, 아직 로드되지 않은 경우 타임아웃이 발생할 수 있습니다.
`.env`의 `LLM_MODEL`을 빈 문자열로 두는 것이 안전합니다.

**GLM-5.2 주의:** 일부 커스텀 백엔드는 `reasoning_content` 필드에 답변을 출력합니다.
`_extract_content()` 함수는 `content` 우선, `reasoning_content` fallback으로 처리합니다.

### 7.7 Local LLM 응답 속도 및 파이프라인 예산

GLM-5.2 (CPU 기반)는 요청당 3~5분이 소요될 수 있습니다. 편수 폭증 시 크론(3시간) 타임아웃 위험이 있으므로 다중 방어 계층을 사용합니다:

**선발 계층 (paper_search.search_all)**
- 후보 수집: `RESEARCH_MAX_RESULTS` (소스×키워드별, 25 권장 — 최종 편수가 아니라 선발 후보 풀)
- 최종 선발: **키워드별 저널 Impact Factor 우선 상위 N건** (`RESEARCH_MAX_PAPERS_PER_KEYWORD`, 기본 5)
  - IF 테이블(`_IMPACT_FACTOR`)에 없는 저널은 기본 8.0, 프리프린트(bioRxiv)는 5.0
  - 인용수 보정: 100회당 +1, 최대 +10 (Semantic Scholar citationCount)
  - 검색 실패/미달 키워드의 몫은 잔여 풀에서 IF 순으로 재배분 (총량 = N × 키워드 수)
- 안전망: `RESEARCH_MAX_TOTAL_PAPERS` (기본 30)

**요약 계층**
- `RESEARCH_TIME_BUDGET_SECS` (기본 7200): 초과 시 남은 논문은 "[시간 예산 초과로 요약 생략]" 표기 후 Slack 전송 (부분 결과 보존)
- `LLM_TIMEOUT_SECS` (기본 600) / `LLM_MAX_RETRIES` (기본 3): 요청당 타임아웃·재시도

### 7.8 Windows 경로 문제

Python에서 `C:/Users/user/...` (Windows 네이티브 경로) 사용. MSYS `/c/...` 경로는 Windows Python이 해석하지 못함.

### 7.9 Slack 채널 ID

채널 이름(`#research-updates`) 대신 **채널 ID**(예: `D0AMMSX1NQ2`)를 사용해야 합니다. `channel_directory.json`에서 DM 채널 ID를 확인하세요.

### 7.10 PDF 전문 처리

bioRxiv는 DOI로 `https://www.biorxiv.org/content/{doi}.full.pdf` 직접 구성, Semantic Scholar는 `openAccessPdf.url`을 사용해 PDF 텍스트(최대 8페이지, 50MB 상한)를 추출한 뒤 fulltext 모드 요약을 시도합니다. 추출 실패/부족 시 abstract 모드로 폴백합니다. Vision LLM 이미지 경로는 제거되었습니다.

---

## 8. 검증 결과 (2026-08-25)

- ✅ `paper_search.py` 실검색 (`tauopathy`, max=2, lookback=1): **PubMed 2건**(pdat 전환으로 복활) + **Springer 2건**(404 폴백/키 정상) + **Elsevier 1건**(ScienceDirect Search V2 신규 엔드포인트, 구 COMPLETE는 401이었음) = 총 5건. Semantic Scholar는 무료티어 429 → for-else로 안전 스킵 확인.
- ✅ 초록 보강 체인: Crossref/OpenAlex에서 DOI당 ~1086자 회수 확인
- ✅ `research_pipeline.py`: 전역 편수 캡(5→3 절단), 시간 예산, Slack 청킹 E2E 스텁 테스트 통과
- ✅ 크론 진입점 사본(`hermes/scripts/research_pipeline.py`) 무한재귀 제거 — 절대경로 위임 래퍼로 교체
- ⚠️ Elsevier/Slack 자격증명이 `.env.example`에 노출된 이력 있음 → **로테이션 권장** (placeholder화 완료)
- ⚠️ hermes venv 업데이트 인터럽트로 소실된 적 있음(2026-08-25) — 재생성 시 `slack-sdk`, `pymupdf` 설치 필요

**주의:** GLM-5.2 (CPU 기반) 요청당 3~5분 소요. §7.7의 예산 계층(`RESEARCH_MAX_TOTAL_PAPERS` 등)을 참고하세요. Springer/Elsevier API key가 없으면 해당 출처 검색이 자동으로 스킵됩니다.

---

## 9. 관련 스킬

- `arxiv` — arXiv 검색 및 메타데이터 추출
- `paper-summary` — PDF 논문 원문/Slack 전송
- `slack-content-sharing` — Slack 전송 패턴 및 `.env` 파싱
- `notebooklm-wiki` — 진화형 `paper_search.py` 원본 (Elsevier SD Search V2, 초록 보강 체인). 드리프트 방지를 위해 양쪽 수정 시 상호 참조할 것.
- `hermes-agent` — Cronjob CLI: `hermes cron create --schedule "0 4 * * *"`

---

## 10. 변경 이력

### v1.1.0 (2026-08-25)
- **크론 타임아웃 근본 수정**: 래퍼 무한재귀 제거(절대경로 위임), 전역 편수 책(`RESEARCH_MAX_TOTAL_PAPERS`), 요약 시간 예산(`RESEARCH_TIME_BUDGET_SECS`), LLM timeout/retries 환경변수화
- **검색 안정화**: Springer for-else NameError, Elsevier 에러엔트리 필터, Retry-After 안전 파싱, bioRxiv 페이징 재작성, 소스별 예외 격리, `&` 키워드 정화, dedup 개선
- **notebooklm-wiki 이식**: Elsevier → ScienceDirect Search API V2(STANDARD view + 헤더 인증), 초록 보강 체인(META→Crossref→OpenAlex), PubMed pdat + itertext, Springer 404/401 폴백·키 마스킹, cp949 콘솔 UTF-8
- **보안**: `.env.example` placeholder화, `.gitignore` 신설

### v1.0.0 (2026-08-19)
- 초기 버전: PubMed/bioRxiv/Semantic Scholar/Springer/Elsevier 통합 검색 + Local LLM 요약 + Slack 알림