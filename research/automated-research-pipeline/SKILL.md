---
name: automated-research-pipeline
description: "Daily paper search, LLM summarize, Slack notify."
version: 1.0.0
author: Hermes Agent
license: MIT
category: research
tags: [Research, Automation, Cron, Slack, Local-LLM, Multi-Source]
related_skills: [arxiv, paper-summary, slack-content-sharing, hermes-agent]
platforms: [linux, macos, windows]
required_environment_variables: [SLACK_BOT_TOKEN]
---

# Automated Research Pipeline

**Trigger:** 매일 정해진 시간에 설정한 주제로 PubMed/bioRxiv/Semantic Scholar/Springer Nature에서 최신 논문을 검색하고, Local LLM으로 요약한 뒤 Slack으로 전송해야 할 때.

**Core:** 다중 출처 통합 검색 → 날짜/키워드 필터링 → Local LLM 요약 → Slack 전송

---

## 1. 아키텍처 패턴

```
[Cron Schedule] ──▶ [research_pipeline.py]
                          │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼              ▼
   출처1 API      출처2 API      출처3 API      출처4 API (선택)
         │              │              │              │
         └──────────────┼──────────────┼──────────────┘
                        ▼
            [날짜 필터 + 키워드 필터링]
                        │
                        ▼
         ┌──────────────┼──────────────┐
         │              │              │
   Local LLM (텍스트)  Vision LLM (이미지)  (fallback)
         │
         └──────────────┼──────────────┘
                        ▼
                    Slack 전송
```

---

## 2. 핵심 설계 원칙

### 2.1 출처별 특성 파악

| 출처 | API 형식 | 날짜 필터 | 키워드 필터 | 비고 |
|------|---------|----------|------------|------|
| **PubMed** | REST (esearch/esummary) | `reldate` + `datetype` | Server-side | UTC 기준 |
| **bioRxiv** | REST (details) | URL path | Client-side (OR 매칭) | 모든 논문 반환 후 필터 |
| **Semantic Scholar** | REST (JSON) | 없음 (최신순) | Server-side | 1req/s rate limit |
| **Springer Nature** | REST (JSON) | `start`/`end` | Server-side (`q="query"`) | 500/day, 100/min 제한 |
| **Elsevier** | REST (JSON) | 없음 (최신순) | Server-side (`query=`) | 100/min, elsapy Archived |

### 2.2 Rate Limit 대응 패턴

```python
# 1. 429 응답 시 Retry-After 헤더 기반 재시도
for attempt in range(max_retries):
    r = requests.get(url, params=params, timeout=60)
    if r.status_code == 429:
        retry_after = int(r.headers.get("Retry-After", "2"))
        time.sleep(retry_after)
        continue
    if r.status_code == 500:
        time.sleep(2 + attempt * 3)  # exponential backoff
        continue
    r.raise_for_status()
    break

# 2. 초과 호출 방지: 호출 간 최소 대기
time.sleep(0.7)  # 100 hits/min = 1req/0.6s → 0.7s 여유
```

---

## 3. Local LLM 최적화 (Critical)

### 3.1 모델명 생략 = 자동 선택 (**가장 중요한 팁**)

CPU 기반 GGUF 모델(Qwen2.5-VL-72B, GLM-5.2 등)은 모델명을 **명시하지 말고 생략**하세요. Ollama가 자동으로 로드된 모델을 사용하며, 모델명을 지정하면 해당 모델을 로드하려는 과정에서 타임아웃이 발생합니다.

```python
# ❌ 시간 초과 위험 (모델명 지정 → 모델 로드 시도)
{"model": "Qwen2.5-VL-72B-Instruct-Q4_K_M", ...}

# ✅ 빠른 응답 (model 파라미터 생략 = 자동 선택)
{"messages": [...]}
```

### 3.2 timeout 설정

CPU 기반 대형 모델은 요청당 3~5분이 소요됩니다. `requests` timeout을 **2400초 (40분)**로 설정하세요.

### 3.3 응답 처리 (.get() 폴백 체이닝)

GLM-5.2 같은 reasoning-only 모델은 `content`가 비어있을 수 있습니다. `.get()` 체인으로 대응:

```python
# ❌ 취약한 추출
content = r.json()["choices"][0]["message"]["content"]

# ✅ robust 추출
choices = r.json().get("choices", [])
msg = choices[0].get("message", {}) if choices else {}
content = msg.get("content") or msg.get("reasoning_content", "") or ""
```

### 3.4 max_tokens 조절

초록 요약은 `max_tokens: 512`면 충분합니다. Vision 요약은 `max_tokens: 1024`.

---

### 4. bioRxiv 키워드 필터링 패턴

bioRxiv은 키워드 검색 API를 지원하지 않습니다. 날짜 범위 내 모든 논문을 가져온 후 클라이언트 측에서 초록/제목에 검색어가 포함되는지 **OR 매칭**으로 필터링합니다. `RESEARCH_LOOKBACK_DAYS=7` 권장 (최근 7일간 검색어 매칭 논문이 적을 수 있음). 자세한 API 응답 구조와 페이지네이션 패턴은 `references/biorxiv_api.md` 참고.

**다중 키워드**: `RESEARCH_TOPIC`에 세미콜론(`;`)이나 쉼표(`,`)로 구분하여 여러 검색어를 설정할 수 있습니다. 각 키워드로 개별 검색 후 결과를 병합 + 중복 제거. 자세한 구현 패턴은 `references/multi_keyword_topic.md` 참고.

---

## 5. Slack 통신 패턴

### 5.1 채널 ID 사용 (채널 이름 ❌)

```python
# ❌ 채널 이름은 Slack API에서 실패
client.chat_postMessage(channel="#research-updates", text=msg)

# ✅ DM 채널 ID 사용
client.chat_postMessage(channel="D0AMMSX1NQ2", text=msg)
```

채널 ID는 `channel_directory.json`에서 확인하세요.

### 5.2 메시지 분할 (2,300자 상한)

```python
MAX_MSG_LEN = 2300
chunks = [msg[i:i+MAX_MSG_LEN] for i in range(0, len(msg), MAX_MSG_LEN)]
for i, chunk in enumerate(chunks):
    client.chat_postMessage(channel=ch, text=f"{chunk}\n\n(계속 {i+1}/{len(chunks)})")
```

---

## 6. Cronjob 설정 패턴

Hermes CLI로 cronjob 등록:

```bash
hermes cron create --schedule "0 4 * * *" \
  --script "run_research_pipeline.bat" \
  --workdir "C:/Users/user/AppData/Local/hermes/skills/research/research_new"
```

### 6.2 Windows 배치 래퍼에서 Hermes 루트 `.env`에서 토큰 자동 로드:

```bat
@echo off
cd /d "%~dp0"
REM Hermes 루트 .env에서 SLACK_BOT_TOKEN 추출
for /f "tokens=*" %%i in ('findstr "SLACK_BOT_TOKEN" "C:\\Users\\user\\AppData\\Local\\hermes\\.env"') do set %%i
"C:\\Python311\\python.exe" scripts/research_pipeline.py
```

**템플릿:** `templates/run_pipeline.bat` — 복사 후 경로만 수정하면 됨. `ERRORLEVEL` 반환으로 cronjob 실패 감지 가능.

---

## 7. Pitfalls

### 7.1 PDF URL은 Vision LLM에 직접 전달 불가

bioRxiv/Semantic Scholar의 PDF URL은 Vision LLM 이미지 처리에 적합하지 않습니다. PDF → 이미지 변환 로직이 별도로 필요합니다.

### 7.2 Windows 경로 문제

MSYS `/c/...` 경로는 Windows Python이 해석하지 못합니다. 네이티브 경로 `C:/Users/...` 또는 bat 래퍼 사용.

### 7.3 출처별 결과가 없을 수 있음

- PubMed: `reldate` 필터로 오늘 발간물이 없을 수 있음
- bioRxiv: 키워드 매칭률이 낮을 수 있음 (lookback_days=7 권장)
- Semantic Scholar: 429 rate limit으로 일부 실패 가능
- Springer/Elsevier: API key 없으면 자동 스킵

**대응:** 각 출처 결과를 독립적으로 처리하고, API key가 없으면 해당 출처를 자동으로 건너뜁니다 (warning 로그만 출력).

### 7.4 Elsevier (elsapy Archived) 특징

- **GitHub 저장소**: https://github.com/ElsevierDev/elsapy (2025년 1월 **Archived**)
- **직접 HTTP 호출 권장**: `https://api.elsevier.com/content/search` with `X-ELS-APIKey` 헤더
- **API key 변수**: `ELSEVIER_API_KEY`
- **Throttling**: 100 Hits/Min (100 hits per minute)
- **401**: API key 무효 → 즉시 중단
- **429**: Rate limit → `Retry-After` 헤더 기반 재시기
- **저자 필드**: `author` 키가 리스트 또는 딕셔너리일 수 있음 → `isinstance` 체크 필요

---

## 8. 구현 템플릿

### 8.1 project structure

```
your_skill/
├── SKILL.md
├── .env
├── .env.example
├── scripts/
│   ├── paper_search.py        # 출처별 검색 + 통합 search_all()
│   ├── local_llm_summarize.py  # LLM 요약 (model 생략, timeout 2400)
│   ├── slack_notifier.py      # Slack 전송 (채널 ID, 메시지 분할)
│   ├── research_pipeline.py   # 메인 오케스트레이터
│   └── run_pipeline.bat       # Windows cron 래퍼
```

### 8.2 paper_search.py 핵심 패턴

```python
@dataclass
class Paper:
    source: str
    paper_id: str
    title: str
    url: str
    abstract: str
    authors: List[str]
    published_date: str
    raw: dict  # 원본 응답 (PDF URL, DOI 등)

def search_all(topic, max_results, lookback_days) -> List[Paper]:
    all_papers = []
    all_papers.extend(search_pubmed(topic, ...))
    all_papers.extend(search_biorxiv(topic, ...))
    all_papers.extend(search_semantic_scholar(topic, ...))
    all_papers.extend(search_springer(topic, ...))
    all_papers.extend(search_elsevier(topic, ...))  # 추가: API key 불필요 시 자동 스킵
    # 중복 제거 (title 정규화)
    seen = []
    for p in all_papers:
        norm = re.sub(r"\s+", "", p.title.lower())
        if norm not in seen:
            seen.append(norm)
            unique.append(p)
```

### 8.3 local_llm_summarize.py 핵심 패턴

```python
# model 빈 문자열 = 자동 선택 (CPU 모델 필수)
DEFAULT_MODEL = ""  # .env에서 빈 문자열

def _build_openai_payload(messages, model, max_tokens, temperature):
    payload = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if model:
        payload["model"] = model  # 빈 문자열이면 제외
    return payload
```

---

## 9. 관련 스킬

- `arxiv` — arXiv 개별 검색 (XML 파싱, BibTeX 생성)
- `paper-summary` — PDF 논문 Slack 분할 전송 (Figure별)
- `slack-content-sharing` — Slack 전송 패턴 및 `.env` 파싱
- `hermes-agent` — Cronjob CLI 및 환경 설정

---

## 10. References

- [Springer Nature API Client](https://github.com/springernature/springernature_api_client) — PyPI: `springernature_api_client`, Open Access / Meta / TDM API 래퍼
- [Elsevier elsapy](https://github.com/ElsevierDev/elsapy) — Archived (2025). Use direct HTTP: `https://api.elsevier.com/content/search` with `X-ELS-APIKey` header.
- bioRxiv API: `https://api.biorxiv.org/details/biorxiv/{start}/{end}/{cursor}/{limit}` (see `references/biorxiv_api.md` for OR-matching pattern)
- Semantic Scholar API: `https://api.semanticscholar.org/graph/v1/paper/search` (1req/s)
- PubMed API: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`

### Springer Nature API 제한

- **Daily Quota**: 500 Hits/Day (API key당 24시간 기준)
- **Throttling**: 100 Hits/Min (분당 최대 요청 수)
- **API key**: `SPRINGER_API_KEY` 환경 변수 또는 `.env`
- **Rate limit 429**: `Retry-After` 헤더 기반 재시도 (최대 3회, exponential backoff)