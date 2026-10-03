---
name: paper-summary
description: PDF 논문 Slack 분할 전송용 스크립트 모음. 원작문+코멘트+요약 순차 전송.
---

# Paper Summary — PDF 논문 Slack 분할 전송 (원문 + 코멘트 + 요약)

**Trigger:** PDF 논문 원고를 섹션/Figure별로 나누어 원문(줄번호 제거)+Reviewer 코멘트+요약을 Slack DM에 순차 전송해야 할 때.

**Core:** PDF 텍스트 추출 → 줄번호 제거 → 섹션 경계 감지 → Results를 Figure subsection 단위로 분할 → 각 섹션마다 `원문 + 코멘트 + 요약` 구분 전송. 핵심은 이미 실행 완료된 스크립트들을 `scripts/`에서 재사용하는 것.

**이 스킬은 기존 `paper-review` 스킬과 함께 본다.** `paper-review`가 "구조·절차·원칙"을 정의한다면, `paper-summary`는 "실제 실행 완료된 스크립트 + 재사용 방법"을 다룬다.

---

## 1. Scripts 디렉토리

스크립트는 이미 `C:\Users\user\AppData\Local\hermes\skills\research\paper-summary\scripts\`에 정리되어 있다. 주요 스크립트:

| 파일 | 용도 |
|---|---|
| `extract_pdf.py` | PDF 텍스트 추출 기본 (fitz, 129페이지) |
| `analyze_pdf_structure.py` | 논문 본문(p.14~51)+reviewer 응답 혼합 구조 파악 |
| `analyze_results_figs.py` | Results Figure subsection 매핑 확인 |
| `find_sections_exact.py` | 섹션 경계 정밀 탐지 (Methods/Results/Discussion) |
| `find_discussion.py` | Discussion 위치 탐색 (Methods 내 Discussion 단어 배제) |
| `find_intro.py` | Introduction 위치 확인 (Abstract 직후) |
| `check_remaining.py` | 누락 subsection 점검 |
| `check_slack_channels.py` | Slack 채널·토큰·권한 확인 |
| `check_env.py` | Slack 연결·토큰 검증 |
| `send_to_slack.py` | 종합 검토 내용 전송용 (초기) |
| `send_abstract.py` | Abstract 추출·전송용 (초기) |
| `send_intro.py` | Introduction 전용 전송 |
| `send_introduction.py` | Introduction 전송 (대안) |
| `send_full_paper.py` | Figure별 분할 전송 (초기 버전) |
| `send_structured.py` | 구조화 전송 로직 (중간 버전) |
| `send_sections_v2.py` | 섹션 경계 정밀 추출·전송 (235 lines) |
| `send_missing.py` | 누락 섹션(Intro, Methods, Fig5, Discussion) 전송 |
| `send_sections_fixed.py` | 섹션 경계 수정 버전 (10K+) |
| `send_sections_reviewer.py` | Reviewer 코멘트 포함 버전 (20K) |
| `send_with_reviewer.py` | 원문 + Reviewer 코멘트 첫 시도 (4.7K) |
| `send_with_reviewer_v2.py` | 원문 + Reviewer 코멘트 v2 (36K) |
| `send_sections_v3.py` | **최신: Methods 내 Discussion 회피 + 원문 + Reviewer 코멘트 전체 전송 (34K, 최종 성공)** |
| `run_*.bat` | bat 래퍼 (venv python + Windows 경로) |
| `list_home.bat` | 홈 디렉토리 파일 목록 조회 |
| `move_files.py` | 홈 디렉토리 파일을 scripts/로 복사하는 도구 |
| `paper_review_summary.txt` | 논문+reviewer 핵심 요약 (56 lines) |

---

## 2. 실행 환경

- **venv python:** `C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe`
- **bat 래퍼 사용:** `run_v3.bat` → Abstract→Introduction→Methods→Results(7개 Figure subsection)→Discussion 순서로 원문+코멘트 전송 완료
- **MSYS `/c/...` 경로 실패:** Windows 네이티브 python이 MSYS 경로를 못 읽음. bat 래퍼 또는 `"C:/..."` + `python.exe` 직접 호출 사용
- **Slack:** `hermes-slack` 플러그인 + `.env` 내 `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` (Socket Mode, 게이트웨이 실행 중·connected, 봇 `payment`, DM 채널 `D0AMMSX1NQ2`)
- **PDF 경로:** `C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf` (129 pages, 60.2 MB)

---

## 3. 재사용 방법

### 3.1 새 PDF로 동일 구조 전송

`send_sections_v3.py`가 현재 가장 완전한 스크립트다. 새 PDF로 재사용 시:

1. PDF 경로 변경: 스크립트 내 `PDF_PATH`를 새 PDF로 변경
2. Slack 채널 확인: 필요시 `channel` 변수 조정 (기본 `D0AMMSX1NQ2`)
3. 실행:
   - bat 래퍼 방식: `"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" "C:\Users\user\AppData\Local\hermes\skills\research\paper-summary\scripts\send_sections_v3.py"`
   - 또는 새 bat 래퍼 작성

### 3.2 전송 순서 조정/일부만 전송

섹션별 전송 순서는 `send_sections_v3.py`의 `[1/5]~[5/5]` 블록을 편집하거나, 더 작은 전용 스크립트(`send_intro.py`, `send_abstract.py` 등)를 개별 실행한다.

### 3.3 줄번호 제거

모든 전송 스크립트에 `remove_line_numbers()` 함수가 포함되어 있다. 단독 줄에 숫자만 있는 행(1~9999)을 제거하고 연속 빈 줄을 2개로 정리한다. 새 PDF로 재사용 시 이 함수를 그대로 사용한다.

---

## 4. 섹션 경계 감지 로직 (핵심)

PDF 구조상 Methods 본문 안에 "Discussion"이라는 단어가 자주 등장해서 섹션 경계가 깨지는 것이 가장 흔한 함정이다.

**해결 패턴:**

1. 먼저 Abstract 위치 확보 (`Background:` 또는 `Abstract`)
2. Methods는 Abstract 이후 첫 "Methods" (cross-reference 문맥 필터: "see methods" 등 제외)
3. Results는 Methods 이후 첫 "Results" (동일 필터)
4. Discussion은 **Results 이후**에서만 검색 + cross-reference 필터
5. Discussion 못 찾으면 Results 직후부터 끝까지를 Discussion으로 fallback

자세한 구현은 `find_sections_exact.py`와 `send_sections_v3.py` 참고.

---

## 5. Results Figure subsection 매핑

Figure별로 나누려면 Figure 설명 문구가 시작되는 위치를 markers로 쓴다. 이 논문 기준:

- Figure 1: "Identification of metastasis-potential cells in primary breast" 
- Supp Fig 3: "To evaluate whether the retained RGSs showed"
- Figure 2: "MPCs exhibit metastasis-associated transcriptional programs"
- Supp Fig 14: "Consistent method-specific differences were also observed"
- Figure 3: "Genomic evolution, cell state dynamics, and regulatory programs"
- Figure 4: "MPCs are predicted to engage specific TME programs"
- Figure 5: "Derivation and validation of an MPC-associated gene signature"
- Supp Fig 10: "MPC identification was then repeated and compared"
- Supp Fig 12: "Consistently, MPCs showed significantly elevated cellular plasticity"
- Supp Fig 13: "To evaluate the impact of MAGIC imputation"

---

## 6. 전송 메시지 구조

각 섹션마다:

```
[섹션 라벨] (예: 📄 Abstract (논문 원문))
원문 (줄번호 제거, 섹션별 분할)

[코멘트 라벨] (예: 💬 Reviewer 코멘트 — Abstract)
원문 요약 + 나의 비평/코멘트
```

문단이 길면 `\n\n` 기준으로 분할, 각 조각에 섹션 라벨 + `(계속)` 라벨을 붙여 여러 메시지로 전송. 메시지 상한 약 2,300자.

---

## 7. Pitfalls

### 7.1 Methods 내 Discussion 단어

- Methods 본문 내 "Discussion"이 Section boundaries를 깨는 가장 흔한 원인
- 해결: Results 이후에만 Discussion 검색 + cross-reference 필터 + fallback

### 7.2 Windows/MSYS 경로

- MSYS `/c/...` 경로로 Windows python 실행 시 `No such file or directory`
- 해결: Windows 네이티브 전체 경로 + bat 래퍼, 또는 WSL 수준에서 실행

### 7.3 긴 메시지

- 한 번에 너무 길면 가독성 저하 + 잘릴 위험
- 해결: 문단 분할 + `(계속)` 라벨

---

## 8. 논문 컨텍스트 (JTRM-D-26-00308R2)

이 스킬이 생성된 계기인 논문의 핵심 컨텍스트:

- **제목:** "Integrative Multi-Modal Transcriptomic Identification of Metastatic Potential Cells Reveals Mechanistic Insights and Pro-Metastatic Ecosystems in Breast Cancer"
- **저널:** Journal of Translational Medicine
- **프레임워크:** scMPC — 전이 관련 마커 + matched primary/metastatic bulk transcriptomes 기반 transfer-learning MPC 식별
- **데이터:** 림프절 전이 유방암 환자 26명 scRNA-seq
- **주요 발견:** MPC 환자 특이적 진화 궤적, 중간엽 가소성 상태, AP-1/KLF6/CEBPD 조절, 공간적 TME 상호작용(C3-C3AR1, VEGFA-VEGFR1 등), MPC 유전자 시그니처와 조기 재발 연관성
- **Reviewer 핵심 지적 및 저자 응답:** 요약 파일에 포함 (causal language 완화, CellChat 주장 완화, CNV "consistent with" 완화, mRNA-based PPI network 명시, ALCAM/VIM/SPARC 독립 검증, "predictor" 용어 삭제+METABRIC Cox)
- **남은 우려 4가지:** RGS 선택 union-based top 10% 위양성 미해소, GSE44408 dual role/threshold-calibration 한정, MAGIC 비의존 MPC 식별 median ARI 0.13, 동시 회귀 ARI 0.21 "overcorrection" 해석 여지

---

## 9. 관련 스킬

- `paper-review` (research 범주): 이 스킬의 원칙·구조 정의. `paper-summary`는 그 실행 버전.
