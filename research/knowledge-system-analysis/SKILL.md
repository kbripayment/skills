---
name: knowledge-system-analysis
description: >
  논문 본문을 완전 정독해 인과 사슬 지식 체계를 재구성하고 인용 논문의 확장 방향을 분석한다.
version: 1.0.0
last_updated: 2026-09-05
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Deep Reading, Knowledge System, Citation Analysis, Paper Analysis]
    category: research
    related_skills: [scholar-citation-search, grounded-citations, arxiv]
    requires:
      tools: [web_extract, read_file]
      env: []
---

# Knowledge System Analysis (본문 정독 기반 지식 체계 재구성)

논문 제목/DOI/URL을 입력받아 **PMC whole-text 또는 OA PDF 전문을 완전히 정독**하고,
논문이 구축한 **인과 사슬 중심의 지식 체계**를 도식화한 뒤,
인용 논문들이 그 체계를 **어떤 방향으로 확장했는지**를 테마별로 분류하여
Obsidian에 저장합니다.

> **설계 원칙**: 이 스킬은 `scholar-citation-search`의 보완재다.
> scholar-citation-search는 "인용 네트워크 → 누가 citing했나"를 보고,
> knowledge-system-analysis는 "논문 자체 → 무엇이 밝혀졌고, 그게 어떻게 발전했나"를 본다.
> 두 스킬은 상호보완적이며, 같은 논문에 연속 적용하면 가장 완전한 그림이 나온다.

## 언제 사용

- "이 논문이 실제로 뭘 밝혔는지 깊이 읽어줘" / "이 논문의 지식 체계를 정리해줘"
- "이 논문을 인용한 후속 연구들이 각각 어떤 방향으로 확장했는지 분석해줘"
- 특정 논문을 중심축으로 한 학문적 지식 전개 지도(knowledge map)가 필요할 때
- scholar-citation-search로 인용 목록을 확보한 후, 그 결과를 더 깊이 분석하고 싶을 때

## When to Use (EN)

- "Deep-read this paper and reconstruct its knowledge system"
- "How did subsequent papers extend the paradigm established by X?"
- Build a knowledge map around a single pivotal paper.

---

## 사전 준비

| 구분 | 필요 여부 | 내용 |
|---|---|---|
| `web_extract` | 필수 | PMC whole-text 또는 OA 논문 랜딩 페이지에서 전문 추출 |
| `read_file` | 필수 | 추출된 텍스트를 오프셋 단위로 페이지 투 페이지 읽기 |
| PMC ID | 권장 | PMCID(예: PMC7497728)가 있으면 `pmc.ncbi.nlm.nih.gov/articles/PMC{id}/`에서 whole-text 확보 |
| DOI | 권장 | DOI가 있으면 OpenAlex로 OA PDF URL 확인 가능 |

> **경로 규칙**: 절대경로 하드코딩 금지. `$HERMES_HOME` 또는 `Path.home()` 기반 상대 경로 사용.

---

## 파이프라인 (5단계)

```
[입력: title | doi | pmc_id | url]
        │
        ▼
┌──────────────────────────────┐
│ ① 논문 식별 & 메타데이터 확보 │  OpenAlex / PubMed / DOI 해석
│  - 정확한 논문 특정 (제목·저자·연도·DOI)│
│  - PMCID, OA 여부, 인용수 확인           │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ② 본문 확보 (2-tier)        │
│  Tier1: PMC whole-text       │  web_extract로 PMC 전문 추출
│    (pmc.ncbi.nlm.nih.gov/articles/PMC{id}/)│
│  Tier2: OA PDF / web_extract │  Nature/Science 등 OA PDF
│    랜딩 페이지에서 본문 추출            │
│  실패 시: abstract만 분석, 명시       │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ③ 본문 정독 & 인과 사슬 추출 │  read_file (병렬 offset)
│  - Introduction: 해결하려는 문제, 기존 지식의 갭│
│  - Results: 핵심 실험, LOF/GOF, rescue │
│  - 각 figure의 논리적 역할 추출         │
│  - Discussion: 저자가 주장한 의의, 한계   │
│  → 인과 사슬(causal chain)로 재구성      │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ④ 지식 체계 도식화           │
│  - 단계별 인과 사슬 (텍스트 다이어그램)   │
│  - 개념 블록 간 관계 시각화 (ASCII 상자)  │
│  - 4~5개의 독창적 기여 포인트 추출       │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ⑤ 인용 논문 확장 방향 분석    │  scholar-citation-search 결과 활용
│  - 인용 논문을 3~6개 테마로 분류         │
│  - 각 테마별 top 인용 논문 + 확장 방식    │
│  - 원 논문의 한계/미해결 과제와 연결      │
│  → "지식 지도" 완성                     │
└──────────────────────────────┘
```

---

## 단계별 상세

### ① 논문 식별 & 메타데이터 확보

- **DOI 우선**: DOI가 있으면 OpenAlex `https://api.openalex.org/works/{doi}`로 정확한 메타데이터 확인
- **PMCID 확인**: PubMed/PubMed Central에 전문이 공개되어 있는지 확인
- **인용수**: OpenAlex `cited_by_count` + `counts_by_year`로 영향력 파악
- **OA 상태**: 전문 확보 가능 여부 판단 (OA 아니면 abstract-only로 강등)

### ② 본문 확보 (2-tier)

**Tier 1 — PMC whole-text (우선)**:
```
web_extract("https://pmc.ncbi.nlm.nih.gov/articles/PMC{id}/")
```
- PMC whole-text는 HTML 형식으로 Introduction, Results, Discussion, Methods 전체가 포함
- 100K~230K chars 규모 — `read_file`로 offset 페이지 투 페이지 읽기 (offset=1 limit=200씩)
- extracted content는 `C:\Users\user\AppData\Local\hermes\cache\web\`에 자동 저장됨

**Tier 2 — OA PDF / 랜딩 페이지**:
- Nature/Science/Cell OA 논문은 `web_extract`로 랜딩 페이지에서 본문 추출 가능
- PDF direct download는 CSP/redirect로 막히는 경우 많음 → web_extract 우선
- PDF download가 필요한 경우: `urllib`으로 다운로드 시도, 실패 시 web_extract로 대체

**실패 시**: abstract만 분석하고 "본문 미확인" 명시

### ③ 본문 정독 & 인과 사슬 추출

**읽을 섹션 우선순위**:
1. **Summary/Abstract** — 논문의 주장 한 문장 요약
2. **Introduction 마지막 단락** — "Here we show..." 형태의 핵심 주장
3. **Results 각 서브섹션 제목** — 실험의 논리적 전개 순서 파악
4. **각 figure legend** — figure가 증명하는 인과 관계 파악
5. **Discussion 첫 단락** — 저자가 주장한 공헌/의의
6. **Discussion 중 "메커니즘" 설명 부분** — 분자적/세포적 기전

**인과 사슬 추출 방법**:
- "A → B → C → D" 형태의 단계적 논리를 찾아냄
- Loss-of-function (cKO, KO, knockdown) 결과로 인과관계 확립한 부분 표시
- Gain-of-function (overexpression, viral delivery) 결과로 충분성 입증한 부분 표시
- Rescue 실험 (ChABC, 약리학적 개입 등) — 인과관계의 결정적 증거로 가장 중요
- 각 figure가 인과 사슬의 어느 단계를 증명하는지 매핑

**추출 포맷 (실행 중 메모)**:
```
[핵심 질문] 논문이 푼 질문 한 문장
[기존 지식 갭] 그 전까지 몰랐던 것
[인과 사슬]
  Step 1: ...  →  증거: Figure X, 실험 Y
  Step 2: ...  →  증거: Figure X, 실험 Y
  ...
[인과관계 확립 방식] LOF / GOF / Rescue / 상관관계
[한계] 저자가 인정한 한계 + 검토자가 볼 수 있는 추가 한계
```

### ④ 지식 체계 도식화

인과 사슬을 **텍스트 다이어그램**으로 시각화:

```
[입력] → [중간 단계 1] → [중간 단계 2] → ... → [최종 결과]
  ↓            ↓                ↓                ↓
 Stimulus    분자 사건 1     분자 사건 2      행동/생리 결과
```

**개념 블록 도식 (ASCII 상자)**:
```
╔══════════════════════════════╗
║  개념 블록 제목               ║
║  - 세부 내용 1               ║
║  - 세부 내용 2               ║
║  - 증거: Fig X, 실험 Y       ║
╚══════════════════════════════╝
```

**독창적 기여 포인트 3~5개 추출**:
- 이 논문이 최초로 밝힌 것
- 기존 패러다임을 전환한 지점
- 방법론적 혁신
- 임상/치료 함의

### ⑤ 인용 논문 확장 방향 분석

`scholar-citation-search`로 확보한 인용 논문 목록을 활용 (또는 새로 수집):

**테마 분류 방법**:
1. 인용 논문의 제목/abstract를 읽어 원 논문의 어떤 측면을 확장했는지 분류
2. 3~6개 테마로 그룹화 (예: ECM 메커니즘 상세화 / IL-33 기능 확장 / 질병 적용 / 발달기 확장 / 5-부분 시냅스 개념 정립)
3. 각 테마별로 가장 많이 인용된 논문 3~5개를 선정
4. 각 테마에서 원 논문의 지식이 어떻게 발전/변형/도전받았는지 서술

**테마 예시 (Nguyen 2020 기준)**:
- ECM/PNN remodeling by microglia
- IL-33의 신경생물학적 기능 확장
- Microglia-synapse interaction 일반 원리
- 5-부분 시냅스(penta-partite synapse) 개념 정립
- 노화/AD에서 ECM-IL-33 축의 병리

---

## 출력 형식

### Markdown / Obsidian (Obsidian Inbox/scholar/에 저장)

````markdown
---
alias: [논문 제목 slug]
tags: [paper-analysis, knowledge-system, <분야>]
source_paper:
  title: "논문 제목"
  doi: "10.xxxx/..."
  pmid: "PMID"
  pmcid: "PMCID (있으면)"
  journal: 저널명
  year: 연도
  authors: [저자 리스트]
collected_at: "ISO8601"
source: "PMC whole-text / OA PDF"
cited_by_count: N
cited_by_total: N (OpenAlex 전체)
analysis_depth: full_text (또는 abstract_only)
---

# 지식 체계 분석: 논문 제목

## 이 논문이 푼 질문

> 한 문장

기존 지식의 갭:
- ...

## 인과 사슬 (Causal Chain)

```
[입력] → [단계 1] → [단계 2] → ... → [결과]
```

### 개념 블록

#### [블록 1 제목]
- 내용
- 증거: Figure X, 실험 Y
- 논리적 역할: 인과 사슬에서 이 블록이 담당하는 기능

#### [블록 2 제목]
...

## 독창적 기여

1. ...
2. ...
3. ...

## 인용 논문의 확장 방향 (테마별)

### 테마 1: [테마명]
- [논문 1] (연도, 인용수) — 확장 방식 설명
- [논문 2] (연도, 인용수) — 확장 방식 설명

### 테마 2: [테마명]
...

## 한계 & 미해결 과제
- 저자 인정 한계: ...
- 추가 한계: ...

---
*분석 방법: PMC whole-text 정독 + 인용 논문 OpenAlex 수집 → 지식 체계 재구성*
*Obsidian 저장: Inbox/scholar/<slug>.md`
````

---

## 제한 사항 & 오류 처리

| 상황 | 대응 |
|---|---|
| PMC whole-text 접근 불가 | DOI로 publisher 사이트 web_extract 시도 → 실패 시 abstract-only 분석 |
| OA PDF 다운로드 403/redirect | web_extract로 랜딩 페이지 본문 추출 시도 |
| 전문이 너무 큼 (>250K chars) | Introduction + Results 핵심 + Discussion + figure legend 우선 읽기 |
| **web_extract char_limit 기본값 부족** | PMC whole-text는 100K~230K chars — `char_limit=None` 또는 250000으로 설정 필수. 기본값 15000으로는 잘림 |
| 영어 외 논문 | 원문 언어 표기, 번역 품질 한계 명시 |
| 인용 논문 1,000+ | 상위 200건 + 연도별 분할 수집 (scholar-citation-search 방식) |
| 인용 논문 abstract 없음 | title + concepts 기반 테마 분류 (정확도 저하 명시) |

---

## 실전 pitfall (2026-09-05 세션 검증)

## scholar-citation-search와의 관계

이 스킬과 `scholar-citation-search`는 상호보완적이다:

```
scholar-citation-search:  논문 X → 누가 인용했나? (네트워크·영향력·검증)
knowledge-system-analysis: 논문 X → 실제로 뭘 밝혔나? (내용·인과사슬·지식전개)
```

**연속 사용 패턴**:
1. 먼저 `scholar-citation-search`로 논문 X의 인용 목록·영향력·검증 확보
2. 그 결과를 입력으로 이 스킬의 ⑤단계에 활용 (인용 논문의 확장 방향 분석)
3. 또는 이 스킬로 논문 X의 지식 체계를 먼저 분석한 후, scholar-citation-search로 인용 맥락 확인

두 스킬의 결과를 같은 Obsidian 노트의 앞뒤 섹션에 함께 저장하면 가장 완전한 그림이 된다.

---

## 관련 스킬

- `scholar-citation-search` — 인용 논문 수집·검증 (이 스킬의 ⑤단계에서 결과 활용)
- `grounded-citations` — 인용 표시 스타일
- `arxiv` — 선행 연구 탐색

---

## 세션 참고 자료

- `references/session-notebook-2026-09-05.md` — 첫 적용 세션(Nguyen 2020)의 실전 패턴·pitfall·결과 요약.

## 변경 이력

- **1.0.0 (2026-09-05)**: 초기 버전. Nguyen et al. 2020 (Cell) 분석 세션에서 확립된
  본문 정독 → 인과 사슬 도식화 → 인용 논문 테마 분류 방법론을 문서화.
