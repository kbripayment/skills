---
name: paper-review
description: PDF 논문을 읽고 reviewer 비평+원문+요약을 Slack에 그림별로 순차 공유할 때
---

# Paper Review Slack Sharing

**Trigger:** 논문 PDF를 읽고 reviewer 스타일로 분석한 내용을 Slack에 공유할 때. 원문(줄번호 제거) + 나의 비평·코멘트 + 핵심 요약을 섹션/그림 단위로 나누어 Slack DM에 순차 전송한다.

**Core:** PDF 텍스트 추출 → 줄번호 제거 → 섹션 경계·Figure subsection 감지 → 각 섹션마다 `원문 + 비평 + 요약`을 구분해 Slack에 순차 전송.

---

## 1. 환경 준비

### 1.1 Slack 연결 확인

Hermes 게이트웨이 상태 확인:

```bash
cat "$HERMES_HOME/gateway_state.json" | python -c "import sys,json; print(json.dumps(json.load(sys.stdin)['platforms'].get('slack',{}), indent=2))"
```

봇 토큰 확인:

```bash
grep -i "SLACK_BOT_TOKEN\|SLACK_APP_TOKEN" "$HERMES_HOME/.env"
```

### 1.2 봇 정보 및 DM 채널 확인

```python
from slack_sdk.web import WebClient
import os, re

env_path = os.path.expanduser("~/.hermes/.env")
env = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            env[key] = val

c = WebClient(token=env.get('SLACK_BOT_TOKEN', ''))
me = c.auth_test()
print(f"봇 이름: {me['user']}")
# DM 채널은 conversations.list(types='im') 또는 기존 채널 ID 사용
```

**실무:** 이 세션에서는 봇(`payment`)과의 DM 채널 `D0AMMSX1NQ2`로 전송.

---

## 2. PDF 텍스트 추출 + 줄번호 제거

### 2.1 추출

```python
from pymupdf import open as fitz_open

doc = fitz_open(PDF_PATH)
pages_text = [doc[i].get_text() for i in range(13, 51)]  # p.14~51 예
doc.close()
raw_text = "\n".join(pages_text)
```

### 2.2 줄번호 제거 (필수)

PDF 추출 텍스트에 페이지를 따라붙는 줄번호(1, 2, 3…)가 남으면 가독성이 나빠진다. **무조건 제거 후 전송.**

```python
import re

def remove_line_numbers(text):
    out = []
    for line in text.split('\n'):
        s = line.strip()
        if s.isdigit() and 1 <= int(s) <= 9999:
            continue  # 줄번호 스킵
        out.append(line)
    cleaned = '\n'.join(out)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # 연속 빈 줄 → 최대 2개
    return cleaned.strip()
```

**Pitfall:** 본문에 진짜로 단독 숫자 행이 있을 수 있다. 그럴 땐 오탐 가능성. 그러나 일반적인 학술 PDF에서는 페이지 끝 줄번호라 위 함수로 충분하다.

---

## 3. 섹션 경계 감지

### 3.1 기본 패턴

```python
def find_section(text, keyword, after_pos=0, exclude_contexts=None):
    for m in re.finditer(rf'\b{re.escape(keyword)}\b', text):
        if m.start() < after_pos:
            continue
        ctx = text[max(0, m.start()-100):m.start()+100]
        ctx_low = ctx.lower()
        if exclude_contexts:
            if any(pat in ctx_low for pat in exclude_contexts):
                continue
        return m.start()
    return None
```

**중요:** Methods 본문 안에 "Discussion"이라는 단어가 쓰인다. 그냥 `find("Discussion")` 하면 Methods 중간을 Discussion 시작으로 잘못 잡는다.

**해결:** 먼저 Methods/Results 위치를 찾고, **Results 이후에만** Discussion을 찾는다. 그리고 "see Discussion", "in the Discussion section" 같은 문맥을 제외한다.

```python
# Methods 찾기 (Abstract 이후)
methods_start = find_section(clean_text, "Methods", abs_pos + 3000,
                             ['see methods', 'in the methods', 'methods section'])

# Results 찾기 (Methods 이후)
results_start = find_section(clean_text, "Results", methods_start + 1000,
                             ['see results', 'in the results', 'results section'])

# Discussion 찾기 (Results 이후, cross-reference 필터)
discussion_start = find_section(clean_text, "Discussion", results_start + 500,
                                ['see discussion', 'in the discussion', 'the discussion section',
                                 'discussion. we', 'discussion, we', 'acknowledging',
                                 'limitation in the discussion', 'revised discussion'])
```

### 3.2 Discussion 못 찾았을 때 fallback

PDF 구조상 Discussion 헤더가 명시되지 않거나, Methods 안 Discussion 단어가 너무 많아 필터링이 과하게 작동할 수 있다. 그럴 땐 **Results 끝난 직후부터 끝까지를 Discussion으로 간주**한다.

```python
if discussion_start is None:
    discussion_start = results_start + len(results_text)
    print("⚠️ Discussion 헤더를 찾지 못함 — Results 이후를 Discussion으로 사용")
```

---

## 4. Results를 Figure subsection으로 분할

Figure별로 나누려면 Figure 설명 문구가 시작되는 위치를 markers로 쓴다.

```python
subsection_markers = [
    ("Figure 1: ...", ["Identification of metastasis-potential cells in primary breast"]),
    ("Supplementary Figure 3: ...", ["To evaluate whether the retained RGSs showed"]),
    ("Figure 2: ...", ["MPCs exhibit metastasis-associated transcriptional programs"]),
    ("Supplementary Figure 14: ...", ["Consistent method-specific differences were also observed"]),
    ("Figure 3: ...", ["Genomic evolution, cell state dynamics, and regulatory programs"]),
    ("Figure 4: ...", ["MPCs are predicted to engage specific TME programs"]),
    ("Figure 5: ...", ["Derivation and validation of an MPC-associated gene signature"]),
    ("Supplementary Figure 10: ...", ["MPC identification was then repeated and compared"]),
    ("Supplementary Figure 12: ...", ["Consistently, MPCs showed significantly elevated cellular plasticity"]),
    ("Supplementary Figure 13: ...", ["To evaluate the impact of MAGIC imputation"]),
]

positions = []
for label, keywords in subsection_markers:
    for kw in keywords:
        pos = results_text.find(kw)
        if pos != -1:
            positions.append((pos, label))
            break
positions.sort(key=lambda x: x[0])

subsections = []
for i, (pos, label) in enumerate(positions):
    start = pos
    end = positions[i+1][0] if i+1 < len(positions) else len(results_text)
    txt = results_text[start:end].strip()
    if txt:
        subsections.append((label, txt))
```

---

## 5. Slack 전송

### 5.1 전송 단위와 길이 제한

- 섹션별로 메시지를 나눈다 (Abstract → Introduction → Methods → Results(Figure별) → Discussion)
- 각 섹션은 **원문 먼저, 그다음 비평/코멘트** 순서로 보낸다
- 섹션 원문이 길면 **문단(\n\n) 단위로 분할**하여 여러 메시지로 보낸다. 각 조각에는 섹션 라벨을 붙이고, 두 번째부터는 `(계속)` 라벨을 붙인다
- 메시지 길이 상한은 약 **2,300자** 정도로 잡는다 (Slack 가독성 + 안전 마진)

### 5.2 전송 코드

```python
from slack_sdk.web import WebClient
import re

c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"  # 봇과의 DM 채널
MAX_MSG = 2300

def send(label, text):
    if not text.strip():
        print(f"  ⚠️ [{label}] 빈 텍스트 — 건너뜀")
        return
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX_MSG:
        resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
        print(f"  ✅ [{label}] → ts={resp['ts']} ({len(msg)} chars)")
        return
    # 문단 분할
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    cur_lbl = label
    buf = ""
    for p in paras:
        trial = f"*{cur_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX_MSG and buf:
            resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"  ✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
            buf = p
            cur_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
        print(f"  ✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
```

### 5.3 전송 순서

1. Abstract (원문 + 코멘트)
2. Introduction (원문 + 코멘트)
3. Methods (원문 + 코멘트)
4. Results — Figure 1 (원문 + 코멘트)
5. Results — Supp Fig 3 (원문 + 코멘트)
6. Results — Figure 2 (원문 + 코멘트)
7. ... (생략된 Figure/Supplement)
8. Results — Figure N까지
9. Discussion (원문 + 코멘트)

---

## 6. 출력 구조: 원문 + 비평 + 요약

기본 출력 단위:

```
[섹션 라벨]          ← 예: 📄 Results — Figure 3: Genomic evolution...
원문 (줄번호 제거)

[비평/코멘트 라벨]   ← 예: 💬 Reviewer 코멘트 — Figure 3
나의 관점:
- 잘 된 점
- 지적 사항 (근거와 함께)
- 확인할 점/질문
- 우려
- (필요시) 관련 Figure/R1-Rn 연결

(필요시) 핵심 요약     ← 2~5문장
```

### 비평에 넣을 요소

- **잘 된 점**: 문서/저자의 강점, 적절한 처리
- **지적 사항**: reviewer로서 문제 삼는 부분, 근거 포함
- **질문/확인 필요**: 추가로 알아봐야 할 것
- **우려**: 해석 과도함, 방법론적 한계, ambiguity
- **문맥 연계**: R1-1, R2-5 같은 reviewer comment 번호, Figure 번호와 연결

---

## 7. Pitfalls

### 7.1 Methods 안 "Discussion" 단어가 섹션 경계 감지 방해

- **증상:** Results, Discussion이 빈 텍스트로 전송됨 / Discussion이 Methods 중간에서 시작됨
- **원인:** `find("Discussion")`가 Methods 본문의 "Discussion"을 먼저 잡음
- **해결:** 섹션 헤더는 앞 섹션 종료 이후에만 검색 + cross-reference 문맥 필터 + fallback 로직

### 7.2 Windows/MSYS 환경에서 Python 실행 경로 문제

- **증상:** heredoc이나 `/c/...` 경로로 실행 시도 시 깨짐 / `python3` 없음
- **해결:** 
  1. heredoc 대신 **별도 `.py` 파일로 작성** 후 실행
  2. `python3` → `python` (또는 venv 내 python)
  3. MSYS bash에서 Windows 네이티브 Python을 **venv 전체 경로 + Windows 네이티브 스크립트 경로**로 실행:
     ```bash
     "C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" "C:\Users\user\script.py"
     ```

### 7.3 긴 메시지 처리

- **증상:** 한 번에 너무 긴 메시지를 보내면 가독성 저하 + 잘릴 위험
- **해결:** 문단을 `\n\n` 기준으로 분할, 각 조각에 섹션 라벨 + `(계속)` 라벨

### 7.4 ROUGE/중복 전송

- **증상:** 이미 보낸 섹션을 다시 보내는 실수
- **해결:** 전송 전 섹션 위치·길이를 로그로 찍고, 전송 완료 표시 명확히. 필요하면 이미 전송된 섹션은 건너뛰는 체크 로직 추가

---

## 8. 예시: 이 세션에서 전송된 구조

```
📄 Abstract (논문 원문)
[원문, 줄번호 제거, 2파트로 분할 전송]

💬 Reviewer 코멘트 — Abstract
[강점, 지적, claim 강도 평가]

📄 Introduction (논문 원문)
[원문]

💬 Reviewer 코멘트 — Introduction
[잘 된 점 3개, 지적 3개, 종합 평가]

📄 Methods (논문 원문)
[원문, 2파트]

💬 Reviewer 코멘트 — Methods
[RGS 선택 위양성, GSE44408 dual role, MAGIC 의존성 등 방법론적 concern]

📄 Results — Figure 1: ...
[원문]

💬 Reviewer 코멘트 — Figure 1
[circularity 관점, patient-specific vs general 관점, 심사 포인트]

... (Figure 2~5, Supp Figs)

📄 Discussion (논문 원문)
[원문, 2파트]

💬 Reviewer 코멘트 — Discussion
[framing 확인 포인트, limitation 정직성, 최종 종합 평가]
```

---

## 10. 관련 파일

- `references/jtrm-d-26-00308-r2-session.md` — 이 세션의 구체적 실행 기록 (전송 ts, 섹션별 길이, 전송 순서 등)
