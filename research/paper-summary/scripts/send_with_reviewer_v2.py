#!/usr/bin/env python3
"""
PDF 논문(p.14~51)에서 섹션별로 원문(줄번호 제거) + Reviewer 코멘트 + 핵심요약
을 Slack DM으로 순차 전송. Abstract → Introduction → Methods → Results(Figure별 + Supp) → Discussion
"""
import re
from pymupdf import open as fitz_open
from slack_sdk.web import WebClient

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
env_path = "C:/Users/user/AppData/Local/hermes/.env"

# env 로드
env = {}
with open(env_path, 'r') as f:
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

# PDF 본문(p.14~51) 추출
doc = fitz_open(PDF_PATH)
pages_text = [doc[i].get_text() for i in range(13, 51)]
doc.close()
raw_text = "\n".join(pages_text)

# ── 줄번호 제거 ──
def remove_line_numbers(text):
    """단독 줄에 있는 1~4자리 숫자(페이지 줄번호)를 제거."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.isdigit() and 1 <= int(stripped) <= 9999:
            continue  # 줄번호 스킵
        cleaned.append(line)
    result = '\n'.join(cleaned)
    # 연속 빈 줄 정리
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

clean_text = remove_line_numbers(raw_text)

# ── 섹션 경계 찾기 ──
def find_section(text, marker, after_pos=0, exclude_context=None):
    """text에서 marker 단어를 섹션 제목으로 가지는 위치를 찾음.
    exclude_context에 속하는 문맥(reviewer 응답/BUG/출처 등)은 제외."""
    for m in re.finditer(rf'\b{re.escape(marker)}\b', text):
        if m.start() < after_pos:
            continue
        ctx = text[max(0, m.start()-120):m.start()+120]
        ctx_low = ctx.lower()
        if exclude_context:
            for pat in exclude_context:
                if pat.lower() in ctx_low:
                    break
            else:
                return m.start()
        else:
            return m.start()
    return None

abstract_start = clean_text.find("Background:")
# "Background:"가 없으면 Abstract로
if abstract_start == -1:
    abstract_start = clean_text.find("Abstract")

# Abstract의 끝 ≈ Introduction 시작 또는 Methods 시작
# 실제 논문 구조: Abstract 다음 Introduction이 명시적 제목 없이 이어짐
intro_end = clean_text.find("Methods", abstract_start + 500) if abstract_start != -1 else -1
intro_text = clean_text[abstract_start+3500:intro_end] if intro_end != -1 else ""

methods_start = clean_text.find("Methods", intro_end + 100) if intro_end != -1 else clean_text.find("Methods", abstract_start + 4000)
results_start = clean_text.find("Results", methods_start + 200) if methods_start != -1 else -1
discussion_start = clean_text.find("Discussion", results_start + 200) if results_start != -1 else -1
references_start = clean_text.find("References", discussion_start + 200) if discussion_start != -1 else -1

print(f"섹션 위치: Abstract={abstract_start}, Intro_end={intro_end}, Methods={methods_start}, Results={results_start}, Discussion={discussion_start}, References={references_start}")

# Methods 이후 실제 Methods 섹션 추출
methods_text = clean_text[methods_start:results_start] if methods_start != -1 and results_start != -1 else ""
results_text = clean_text[results_start:discussion_start] if results_start != -1 and discussion_start != -1 else ""
discussion_text = clean_text[discussion_start:references_start] if discussion_start != -1 and references_start != -1 else ""

print(f"\n섹션 길이: Intro={len(intro_text)}, Methods={len(methods_text)}, Results={len(results_text)}, Discussion={len(discussion_text)}")

# ── Results를 Figure subsection으로 분할 ──
# subsection 식별 키워드와 라벨
subsection_markers = [
    ("Figure 1: Identification of metastasis-potential cells in primary breast Tumors using scMPC",
     ["Identification of metastasis-potential cells in primary breast", "Identification of metastasis-potential cells in primary"]),
    ("Supplementary Figure 3: RGS permutation null analysis",
     ["To evaluate whether the retained RGSs showed"]),
    ("Figure 2: MPCs exhibit metastasis-associated transcriptional programs across multiple biological dimensions",
     ["MPCs exhibit metastasis-associated transcriptional programs"]),
    ("Supplementary Figure 14: Method comparison (Scissor/LP_SGL/SCIPIC 등)",
     ["Consistent method-specific differences were also observed"]),
    ("Figure 3: Genomic evolution, cell state dynamics, and regulatory programs of MPCs",
     ["Genomic evolution, cell state dynamics, and regulatory programs"]),
    ("Figure 4: MPCs are predicted to engage specific TME programs",
     ["MPCs are predicted to engage specific TME programs"]),
    ("Figure 5: Derivation and validation of an MPC-associated gene signature",
     ["Derivation and validation of an MPC-associated gene signature"]),
    ("Supplementary Figure 10: MPC 식별 안정성 + 회귀 민감도 분석",
     ["MPC identification was then repeated and compared"]),
    ("Supplementary Figure 12: CytoTRACE2 분석",
     ["Consistently, MPCs showed significantly elevated cellular plasticity"]),
    ("Supplementary Figure 13: MAGIC imputation 영향 평가",
     ["To evaluate the impact of MAGIC imputation"]),
]

# 위치 찾기
subsection_positions = []
for label, keywords in subsection_markers:
    for kw in keywords:
        pos = results_text.find(kw)
        if pos != -1:
            subsection_positions.append((pos, label, kw))
            break

subsection_positions.sort(key=lambda x: x[0])

# 분할
subsections = []
for i, (pos, label, kw) in enumerate(subsection_positions):
    start = pos
    end = subsection_positions[i + 1][0] if i + 1 < len(subsection_positions) else len(results_text)
    txt = results_text[start:end].strip()
    if txt:
        subsections.append((label, txt))

if not subsections:
    subsections = [("Results (전체)", results_text)]

print(f"\nResults → {len(subsections)}개 subsection:")
for label, txt in subsections:
    print(f"  [{label}] {len(txt)} chars")

# ── Slack 전송 함수 ──
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX_MSG = 2300  # Slack 메시지 길이 안전 상한

def send_to_slack(label, text):
    """블록 하나를 Slack에 전송 (길면 분할)."""
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX_MSG:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"✅ [{label}] → ts={resp['ts']} ({len(msg)} chars)")
            return
        except Exception as e:
            print(f"❌ [{label}] 전송 실패: {e}")
            return
    
    # 분할 전송
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    current_label = label
    buffer = ""
    
    for para in paragraphs:
        trial_msg = f"*{current_label}*\n\n" + (buffer + "\n\n" + para if buffer else para)
        if len(trial_msg) > MAX_MSG and buffer:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{current_label}*\n\n{buffer}", parse="mrkdwn")
                print(f"✅ [{current_label}] → ts={resp['ts']} ({len(buffer)} chars)")
            except Exception as e:
                print(f"❌ [{current_label}] 전송 실패: {e}")
            buffer = para
            current_label = f"{label} (계속)"
        else:
            buffer = (buffer + "\n\n" + para).strip() if buffer else para
    
    if buffer:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{current_label}*\n\n{buffer}", parse="mrkdwn")
            print(f"✅ [{current_label}] → ts={resp['ts']} ({len(buffer)} chars)")
        except Exception as e:
            print(f"❌ [{current_label}] 전송 실패: {e}")

# ── 전송 순서 ──
print("\n" + "="*60)
print("SLACK 전송 시작 (원문 + Reviewer 코멘트 + 요약)")
print("="*60)

# 1. Abstract
print("\n[1/7] Abstract")
abstract_text = clean_text[abstract_start:abstract_start+3500] if abstract_start != -1 else ""
send_to_slack("📄 Abstract (논문 원문)", abstract_text[:3000])

abstract_comment = """*🔍 Reviewer 코멘트 — Abstract*

**요약:**
- scMPC: bulk matched primary-metastasis transcriptomes + scRNA-seq → 환자별 MPC 식별
- 26명 림프절 전이 유방암 환자 scRNA-seq
- MPC: 환자 특이적 진화 궤적, 중간엽 가소성 상태, AP-1/KLF6/CEBPD 조절, 공간적 TME 상호작용
- MPC 유전자 시그니처 → 조기 재발 연관

**Reviewer 관점:**
- Abstract는 대체로 hypothesis-generating 프레임으로 잘 정리됨. "identify", "characterize", "provide insights" 정도의 표현 수준.
- 다만 "MPCs shape a pro-metastatic tumor ecosystem" 류의 표현이 Abstract에 있다면(실제 확인 필요) R1-1에서 지적된 과잉 서술. Abstract 수준에서는 보통 결과를 압축하다 보니 이런 표현이 들어가기도 함.
- "mechanism" 단어 사용 시 계산적 예측임을 암시하는지 확인 필요.

**주장 강도 평가: Abstract는 전반적으로 acceptable 수준. 인과적 과잉 표현이 있다면 R1 지적에 따라 수정된 버전이 반영되었는지 확인."""

send_to_slack("💬 Reviewer 코멘트 — Abstract", abstract_comment)

# 2. Introduction
print("\n[2/7] Introduction")
send_to_slack("📄 Introduction (논문 원문)", intro_text[:3000])

introduction_comment = """*🔍 Reviewer 코멘트 — Introduction*

**요약:**
- 림프절 전이의 중요성 → 전이 가능 세포의 기전 규명 필요성
- EMT/pEMT의 역할 + 한계 → "spectrum of highly plastic cell states"로 패러다임 확장
- MICs(metastasis-initiating cells) 개념, TME 재구성
- bulk transcriptomics의 한계, scRNA-seq의 가치
- scMPC 제시: bulk + scRNA-seq 통합 프레임워크, 26명 paired 데이터로 MPC 식별 + 특성 규명

**Reviewer 관점 (찬성):**
- 배경 서술이 최신 문헌을 반영하며 논리 전개가 매끄러움.
- EMT 단일 패러다임에서 "plasticity spectrum"으로의 전환은 현재 필드에서 설득력 있는 프레임.
- "future functional investigation"이라는 표현 — 발견을 가설 생성 수준으로 위치시킴. Good.

**Reviewer 관점 (지적 사항):**
1. MICs vs MPC 용어 관계 — Introduction에서 MICs는 일반적 개념, MPC는 scMPC로 식별된 구체적 세포군으로 구분되는지 명확하지 않음. 용어 정의/관계 정립이 있으면 좋겠다.
2. "actively remodel the TME" 표현(73-75라인 부근) — R1-1에서 지적된 causal language의 전형. 서론에서 배경 문헌 리뷰 수준이므로 용인될 여지는 있으나, "associated with", "recruit/repurpose stromal components" 정도로 완화 가능.
3. "providing insights into the molecular programs associated with metastatic competence" — 적절한 수준의 주장. 그러나 "mechanisms underlying"라는 표현은 조심할 필요. 계산적 연구에서 "mechanism"을 주장할 때는 그 한계를 명확히 하는 게 좋음.

**종합:** Introduction은 대체로 잘 쓰였고, claim 강도도 acceptable. 언급된 2개 포인트를 정리하면 더 견고해짐."""

send_to_slack("💬 Reviewer 코멘트 — Introduction", introduction_comment)

# 3. Methods
print("\n[3/7] Methods")
send_to_slack("📄 Methods (논문 원문)", methods_text[:3000])

methods_comment = """*🔍 Reviewer 코멘트 — Methods*

**요약:**
Methods 섹션은 scMPC 프레임워크의 전체 파이프라인을 기술:
- Bulk 데이터 처리 (GEO 검색, paired primary-metastasis 데이터셋 선별)
- Random Gene Set (RGS) 발견 절차: Monte Carlo 샘플링, balanced dataset 구성, RGS 평가 (AUC, balanced accuracy, MCC, Kappa), 100만 개 RGS 중 union-based top 10% 선택
- Gene ranking: 각 RGS 내 유전자별 성능 기여도 → cross-dataset Robust Rank Aggregation (RRA) → 22개 M_signatures 최적화
- scRNA-seq 처리: SCT 정규화, MAGIC imputation (선택), 앙상블 클러스터링 (k-means + 계층적 consensus), MPC 식별
- CNV 추론: inferCNV 사용, clonal architecture 추론
- Pseudotime: Monocle2 + scTour
- Ligand-receptor: CellChat, 공간 전사체 co-localization
- GRNBoost2 기반 TF-target 규제 네트워크, differential edge 분석 (permutation test)
- MPC 시그니처 도출: STRING PPI 네트워크 (v12.0, confidence ≥0.700), Cytoscape cytoHubba 12개 알고리즘 → 22개 유전자
- 임상 연관 분석: METABRIC ssGSEA, Cox proportional-hazards (36개월 censoring, multivariable), TCGA-BRCA는 제거됨
- 검증: permutation null, bootstrap CI, forward feature selection, sensitivity analyses (regression, cluster 파라미터, gene threshold, MAGIC, 방법 비교)

**Reviewer 관점:**

**잘 된 점:**
- 파이프라인 단계별로 Methods에 기술된 점 전반적으로는 양호.
- RGS 발견 절차에서 balanced dataset 구성, evaluation metrics 다중 사용, RRA 통합 과정이 투명하게 기술됨.
- Methods 3.2에서 signature optimization 근거와 민감도 분석(top 30/50/70) 설명.
- 임상 분석 Methods에서 censoring-aware approach, multivariable 조정 변수, NPI sensitivity model 구체적.
- Supplementary에 추가된 분석(부트스트랩 CI, permutation, 회귀 민감도, MAGIC 비교, 방법 비교)이 Methods 레벨에서 적절히 언급됨.

**보완이 필요한 부분:**

1. **RGS 선택 위양성률 (R2-1, R1-4)**
   - Methods에 "100만 개 RGS 중 union-based top 10%" 절차가 기술되어 있지만, 이 선택 규칙의 FPR에 대한 formal control은 없음.
   - 저자는 supplementary에서 permutation null을 "민감도 평가"로 추가했지만 Methods 자체에는 여전히 선택 규칙이 primary. 이 부분을 Methods에서 어떻게 기술할지 고민 필요 — 예: "RGS selection was performed using a union-based criterion, and the retained sets were subsequently evaluated against a permutation-derived empirical null (Supplementary Figure 3)."

2. **GSE44408의 dual role (R2-2)**
   - Methods 3.2: "GSE44408을 threshold-tuning dataset으로 사용"이라고 명시 → 개선됨.
   - 그러나 discovery 단계에서도 GSE44408이 gene ranking에 기여했다는 점 → 완전히 독립적인 threshold tuning은 아님.
   - 이 점을 Methods에서 "threshold calibration"임을 강조하되, discovery 기여도 또한 명시하면 더 투명.

3. **MAGIC imputation 의존성 (R2-5)**
   - Methods에 "MAGIC imputation was applied to enhance signal recovery"라고 되어 있을 텐데, 이 선택이 MPC 식별에 결정적 영향(median ARI 0.13 without MAGIC)을 미친다는 결과가 supplementary에 있음.
   - Methods 자체적으로 imputation 선택의 근거와 민감도를 언급할지 검토 필요.

4. **inferCNV 한계 (R1-1B)**
   - Methods에 inferCNV 사용 기술 + 참조 세포 선택 방법 등이 있을 것. CNV inference가 clonal origin 주장에 어떻게 연결되는지에 대한 방법론적 한계 설명이 Methods에 있는지 확인 필요.

5. **PPI 네트워크 파라미터 (Minor f)**
   - Methods에 STRING v12.0, confidence ≥0.700, 12개 topological algorithms, 상위 20개 → ≥4개 알고리즘에서 공통 → 22개 시그니처. 이제는 명시됨(저자 수용). Good.

6. **부트스트랩 CI (Minor i)**
   - Methods에 "1,000 bootstrap resamples, percentile CI" 명시됨(저자 수용). Good.

**종합:** Methods는 전반적으로 기술적 재현성을 갖춘 수준. RGS 선택 위양성, MAGIC 의존성, GSE44408 dual role이 가장 중요한 methodological concern."""

send_to_slack("💬 Reviewer 코멘트 — Methods", methods_comment)

# 4. Results — Figure별
print("\n[4/7] Results (Figure별 subsection)")
for i, (label, text) in enumerate(subsections):
    print(f"\n  [{i+1}/{len(subsections)}] {label}")
    send_to_slack(f"📄 Results — {label}", text[:3000])

# 각 Figure별 reviewer 코멘트
results_comments = {
    "Figure 1: Identification of metastasis-potential cells in primary breast Tumors using scMPC": """*🔍 Reviewer 코멘트 — Figure 1*

**내용 요약 예상:**
- scMPC 프레임워크 개요 (Figure 1a)
- 26명 환자 scRNA-seq 데이터에서 환자별 MPC 식별 결과 (Figure 1b-e)
- MPC 비율, 클러스터 분포, M_signature 활동 등

**Reviewer 코멘트:**

**R1-2(circularity) 관점에서:**
- Figure 1에서 MPC 식별 결과가 EMT, invasion, metastasis score로 "검증"되는 패턴이 있다면 circularity 지적 대상.
- 저자들이 ALCAM/VIM/SPARC를 독립 마커로 분리했는지, Figure 1에서 독립 검증 마커가 강조되는지 확인 필요.

**R1-1B(patient-specific vs general) 관점에서:**
- Figure 1이 "13개 primary tumors에서 MPC 식별"을 보여줌 → 환자 특이적 vs 공통 특징의 구분이 시각적으로도 드러나야 함.
- 저자 응답: "MPCs identified in all 13 patients" → scMPC가 전체 환자에서 작동한다는 주장. 이 자체가 "universal"임을 증명하지는 않으나, 적어도 환자 간 이질성 속에서도 식별은 됨을 보여줌.

**심사 포인트:**
- Figure 1에서 MPC 식별의 신뢰도를 보여주는 evidence (stability, cluster quality)는 무엇인지.
- "distinct patient-specific evolutionary trajectories"라는 서술이 Figure 1에서 어떻게 뒷받침되는지. Patient별 세부 결과가 Figure 1에 포함되는지, 아니면 후속 Figure에서 나오는지.""",

    "Supplementary Figure 3: RGS permutation null analysis": """*🔍 Reviewer 코멘트 — RGS permutation null (Supp. Fig. 3)*

**내용 요약 예상:**
- 100만 개 RGS 중 union-based top 10% 선택된 RGS들 대상
- 500회 label permutation → empirical null 분포
- Selected RGS들의 성능이 random보다 유의미하게 높은지 평가 (empirical P + BH 보정)

**Reviewer 코멘트 (R1-4, R2-1):**

**저자 대응 평가:**
- RGS 선택 **후** permutation 평가 → 선택 과정의 FPR control은 아님.
- "Retained RGSs generally exceeded random expectation" → 선택적 편향 후 평가에서 노이즈 아님을 보임.
- 작은 데이터셋은 유의하지 않음 → power issue로 해석. 저자는 "additional filtering은 underpowered dataset에 해롭다"고 방어.

**Reviewer 관점:**
- 이 접근의 한계는 분명하나, 선택된 RGS가 전혀 근거 없는 noise는 아니라는 evidence로는 기능.
- 단, "permutation filtering을 추가적 선택 기준 삼지 않음"이라는 저자의 판단 → 적절한 scope 판단일 수 있으나, 이 논문을 "prediction model"로 포지셔닝하려면 더 stringent control이 필요했을 것. 현재 "clinical association" 프레임에서는 acceptable.

**핵심 질문:**
- permutation test에서 어떤 RGS가 살아남고 어떤 게 탈락하는지, 데이터셋별 차이가 있는지 → 이 정보가 supplementary에 제대로 있는지.""",

    "Figure 2: MPCs exhibit metastasis-associated transcriptional programs across multiple biological dimensions": """*🔍 Reviewer 코멘트 — Figure 2*

**내용 요약 예상:**
- MPC vs NPC 비교: EMT, invasion, metastasis signature, 세포 가소성(plasticity), 줄기세포 마커(ALCAM, VIM, SPARC, SOX9, NEAT1, CCL5)
- high-plasticity cell state program
- CytoTRACE2: 4/13 환자에서만 유의

**Reviewer 코멘트:**

**R1-2(circularity) — 가장 핵심:**
- Figure 2에서 MPC "검증" 방식으로 EMT/침습/전이 score를 사용하는 부분이 있다면 순환성 문제.
- 저자 수정: ALCAM/VIM/SPARC = 독립 마커(22개 M_signatures에 없음), SOX9/NEAT1/CCL5 = supportive only. 이 구분을 Figure 2에서 명확히 하는지 확인.
- "MPCs exhibit pronounced metastatic capacity"는 R1이 "metastasis-associated transcriptional programs"로 순화 요청 → Figure 2 제목/legend에서 반영 여부.

**R1-5(regression sensitivity) 연계:**
- Cell cycle, hypoxia, stress response 제거한 후에도 MPC 특성이 유지되는지에 대한 민감도 분석 결과가 Figure 2 관련 supplementary에 포함.
- 개별 제거 시 유지되나, 동시 제거 시 ARI 0.21로 하락 → Figure 2 해석을 할 때 이 점을 감안해야 함: MPC가 이들 프로그램과 완전히 독립적이지 않음.

**CytoTRACE2 (Minor g):**
- 13명 중 4명만 유의 → 저자: "patient-dependent support for increased developmental potential"으로 표현 조정. Good.
- CytoTRACE가 developmental potency 측정 → 암세포 전이 가소성과 직접 연결은 제한적. 이 한계를 discussion/legend에서 인지하는지.""",

    "Supplementary Figure 14: Method comparison (Scissor/LP_SGL/SCIPIC 등)": """*🔍 Reviewer 코멘트 — 방법 비교 (Supp. Fig. 14)*

**내용 요약 예상:**
- Scissor: 3/13 환자에서만 phenotype-associated cells 식별
- scAB: 13/13, scPAS: 11/13, LP_SGL: 7/13, SCIPIC: 10/13
- scMPC: 13/13
- 방법 간 overlap 분석

**Reviewer 코멘트 (Minor 6):**

**저자 대응 평가:**
- "세 방법이 비슷한 결과를 보였다"는 원문의 과도한 일반화를 삭제 → 구체적 patient-level 결과 제시.
- Scissor의 낮은 coverage(3/13) vs scMPC 13/13 → scMPC의 장점으로 해석 가능하나 주의 필요.

**Reviewer 관점:**
- "환자에서 phenotype-associated cells 식별"만으로 방법의 우월성을 주장하기에는 부족.
- Scissor가 coverage 낮은 이유: bulk reference 품질? phenotype 정의? 방법론적 한계?
- 방법 간 overlap이 낮은 이유: 각 방법이 다른 transcriptional signal에 의존하기 때문 → 이게 scMPC의 "독립성"을 입증하는지, 아니면 그냥 다른 기준일 뿐인지.

**주의점:**
- scMPC가 13/13이라고 해서 "더 정확하다"는 보장은 없음 — gold standard 없으므로 환자 coverage는 하나의 기준일 뿐.
- 이 section은 "scMPC가 다양한 complementary 방법과 비교하여 일관된 MPC-like 집단을 식별한다" 정도의 framing이 적절.""",

    "Figure 3: Genomic evolution, cell state dynamics, and regulatory programs of MPCs": """*🔍 Reviewer 코멘트 — Figure 3*

**내용 요약 예상:**
- CNV 기반 clonal architecture (inferCNV)
- Pseudotime trajectory (Monocle2 + scTour)
- TF-target regulatory network (GRNBoost2), differential edge 분석
- AP-1(FOS/JUN), KLF6, CEBPD 등 regulatory 프로그램

**Reviewer 코멘트:**

**R1-1B — clonal origin 주장 (가장 중요):**
- "MPCs originated from multiple subclones" → "consistent with CNV-inferred monoclonal/polyclonal emergence"으로 완화되었는지.
- "17q gain likely drove metastasis" → "candidate genomic alterations associated with metastatic competence" 수준으로 완화되었는지.
- Figure 3에서 CNV 분석이 clonal origin의 **증거**처럼 제시되는지, 아니면 "consistent with" 패턴으로 제시되는지.

**Pseudotime (R1-1B):**
- Monocle2 primary, scTour sensitivity check → "inferred transcriptional progression, not direct developmental history"라는 framing.
- Trajectory 상 MPC 위치("early/late") 주장이 definitive 하게 제시되는지, 아니면 "occupy transcriptional states ordered along inferred pseudotime" 수준인지.

**Regulatory network (R1-1C, R1-5):**
- GRNBoost2 기반 TF-target edge → mRNA 발현 기반 추론. 단백질 수준 검증 아님.
- R1-5에서 지적된 "95% CI" → "95% permutation-null interval"로 수정.
- 유의성 threshold: empirical P < 0.05 → BH FDR < 0.05 → 6 edges만 통과 (42 edges nominal). 보수적.
- Figure 3에서 regulatory edge들이 "validated regulatory interactions"처럼 제시되는지, 아니면 "computationally inferredcandidate interactions"로 제시되는지.

**핵심 question:**
- Figure 3의 narrative가 "evolutionary history를 재구성했다"는 인상을 주는지, 아니면 "transcriptional dynamics와 regulatory programs의 연관성을computational하게 탐색했다"는 인상을 주는지. 전자라면 R1 지적에 위배.""",

    "Figure 4: MPCs are predicted to engage specific TME programs": """*🔍 Reviewer 코멘트 — Figure 4*

**내용 요약 예상:**
- CellChat 기반 ligand-receptor 상호작용 예측
- ECM-receptor (51%), cell-cell contact (26%), secreted signaling (23%)
- VEGFA-VEGFR1 (pt 180-3), C3-C3AR1 (pt 195-1), CXCL12 (pt 161-5) 등
- 공간 전사체 co-localization

**Reviewer 코멘트 (R1-1A — 가장 핵심):**

**저자 대응 평가:**
- "MPCs shape a pro-metastatic tumor ecosystem" → "MPCs are predicted to engage specific TME programs" / "associated with pro-metastatic TME states"로 완화.
- "signaling interactions" → "predicted ligand-receptor interactions"
- Discussion에 "단백질 수준 공간 assay + functional co-culture/in vivo 검증 필요" 명시.

**Reviewer 관점:**
- CellChat은 mRNA 발현 기반 ligand-receptor pairing 예측 → 물리적/기능적 상호작용의 **증거가 아님**. 이 점이 Figure 4에서 명확히 전달되어야 함.
- VEGFA-VEGFR1, C3-C3AR1, CXCL12 등이 단일 환자 관찰이라는 점 → 일반화된 주장으로 확장하지 않았는지.
- "more than half (51%) belonging to ECM-receptor category" 정량화 (Minor h, 저자 수용) → Figure 4 범례에 명확해야 함.

**공간 co-localization:**
- 전사체 수준 co-localization ≠ 단백질 수준 물리적 상호작용.
- Figure 4가 이 한계를 인지한 tone으로 제시되는지.

**종합:**
- Figure 4는 "예측된 상호작용의 landscape"를 보여주는 데 초점. "TME를 actively remodel한다"는 주장이 빠졌다면 적절한 수준의 결과 제시.
- 다만, 이러한 예측들이 "hypothesis-generating" 목적임을 figure legend와 discussion에서 반복적으로 명시하는지 확인.""",

    "Figure 5: Derivation and validation of an MPC-associated gene signature": """*🔍 Reviewer 코멘트 — Figure 5*

**내용 요약 예상:**
- MPC 시그니처 도출 과정 (STRING PPI → 22개 유전자)
- MetMap500에서 weak/highly metastatic lines 비교
- METABRIC ssGSEA + Cox 분석 (HR=1.17, P=0.011)
- TCGA-BRCA 제거됨

**Reviewer 코멘트:**

**R1-1C — mRNA→PPI (가장 중요):**
- "mRNA-derived, PPI-prioritized candidate signature"로 명시되었는지.
- STRING v12.0, confidence ≥0.700, cytoHubba 12개 알고리즘, ≥4개 알고리즘에서 공통 → 22개. 파라미터 투명해짐 (Minor f, 저자 수용).
- 6개 유전자만 Human Protein Atlas 교차 참조 → 제한적. 이 한계를 discussion에서 인지하는지.

**R1-3 — 임상 주장 (가장 중요):**
- "predictor", "independent predictor", "clinically actionable" → 모두 삭제됨. "Derivation and validation of an MPC-associated gene signature"으로 섹션 제목 변경.
- METABRIC Cox: HR=1.17 (1.04-1.32, P=0.011), NPI-adjusted HR=1.16 (1.03-1.31, P=0.015)
- TCGA-BRCA 분석 제거됨 (조정 후 유의하지 않음). 어려운 결정이었으나 적절.
- "clinical association" ≠ predictive performance → 명확하게 구분됨.

**R1-4, R2-1 — RGS 선택:**
- Figure 5의 시그니처 도출은 RGS→RRA→22개 유전자. RGS 선택의 위양성 문제가 이 시그니처의 신뢰도에 영향.
- Supplementary Fig 3의 permutation 분석에서 smallest dataset 유의하지 않음 → 시그니처 도출의 기반이 일부 약한 데이터셋 포함.

**MetMap500 (Minor d):**
- Weakly metastatic lines에서 highest score → "early acquisition" 가설.
- 저자 수정: "may capture transcriptional programs associated with early metastatic progression, although further functional studies are required... alternative biological explanations also possible" → balanced.

**부트스트랩 CI (Minor i):**
- Figures/Results에 AUC, balanced accuracy, precision, F1에 대한 95% bootstrap CI 포함 (1,000 resamples, percentile method). Good.

**종합:**
- Figure 5는 가장 임상적으로 의미 있는 섹션. 그러나 주장의 강도는 "clinical association" 수준으로 제한되어야 함. "predictive signature"라는 positioning은 현재 데이터로는 과장.""",

    "Supplementary Figure 10: MPC 식별 안정성 + 회귀 민감도 분석": """*🔍 Reviewer 코멘트 — MPC 식별 안정성 + 회귀 민감도 (Supp. Fig. 10)*

**내용 요약 예상:**
- Random seed 변경 → ARI/NMI/Jaccard = 1.00 (완전 일치)
- Cluster 수 범위 확장(12) → median ARI 0.98, NMI 0.95, Jaccard 0.99
- Linkage: Ward.D → ARI 0.89, average → ARI 0.39 (민감도 높음)
- Gene retention threshold: top 30 → ARI 0.79, top 70 → ARI 0.95
- Cell cycle / hypoxia / stress response 개별 회귀 → ARI 0.44-0.57, Jaccard 0.62-0.74 (대체로 유지)
- 동시 회귀 → ARI 0.21, NMI 0.15, Jaccard 0.57 (급감)

**Reviewer 코멘트:**

**R2-4 (안정성 정량화) — 저자 대응 양호:**
- Previously "highly stable across all perturbation settings" → 구체적 수치로 대체.
- Average linkage의 민감도(ARI 0.39)가 상당히 높음 → linkage 선택이 결과에 영향.
- 이 정보를 투명하게 제시한 점 좋음.

**R1-2 (회귀 민감도) — 남은 우려:**
- 개별 프로그램 제거 시 MPC labels 대체로 유지 → "no single canonical program drives MPC identification" 주장 지지.
- **동시 제거 시 ARI 0.21 급감 → 저자의 "overcorrection, biologically intertwined" 해석.**
- Reviewer 관점: 이 결과는 MPC가 이들 프로그램과 독립적이지 않다는 signal. 저자의 해석은 부분적 타당성 있으나, 순환성 지적을 완전히 해소하지는 않음.
- Discussion에서 이 점을 "MPC 정체성과 canonical program의 생물학적 연관성"으로 정직하게 다루는지 확인 필요.

**핵심 질문:**
- "동시 회귀 시 ARI 0.21"을 이 논문의 맥락에서 어떻게 해석할지가 중요. 저자는 "지나친 보정"이라고 주장하나, reviewer는 "MPC 정의가 이들 프로그램과 상당히 얽혀있다"는 대안적 해석 가능.""",

    "Supplementary Figure 12: CytoTRACE2 분석": """*🔍 Reviewer 코멘트 — CytoTRACE2 (Supp. Fig. 12)*

**내용 요약 예상:**
- 13명 중 4명(161_3, 161_5, 180_3, 180_5)에서만 MPC가 NPC보다 유의하게 높은 CytoTRACE2
- 나머지 9명에서는 유의 차이 없음

**Reviewer 코멘트 (Minor g):**

**저자 대응 평가:**
- "일관된 plasticity 증거"라는 표현을 "patient-dependent support"로 수정 → Good.
- CytoTRACE2의 한계를 인지: developmental potency 측정 → 암세포 전이 가소성과 반드시 연관되지 않음.

**Reviewer 관점:**
- 4/13만 유의한 것은 놀라운 일 아님. CytoTRACE가 주로 발달 potency 포착 → 암세포에서는 다른 factor가 더 dominant할 수 있음.
- 이 heterogeneity가 "MPCs는 homogeneous high-plasticity state"라는 단순 서사를 약화함.
- 이 결과가 MPC 개념의 robustness에 대해 시사하는 바: 일부 환자에서 MPC가 진정한 high-plasticity state가 아닐 수 있음. Acknowledge 필요.""",

    "Supplementary Figure 13: MAGIC imputation 영향 평가": """*🔍 Reviewer 코멘트 — MAGIC imputation 영향 (Supp. Fig. 13)*

**내용 요약 예상:**
- Non-imputed 데이터로 scMPC 재실행
- Median ARI 0.13 (범위 -0.03~1.00), NMI 0.19, Jaccard 0.52
- 일부 환자(167_8, 180_5)는 거의 일치, 다른 환자는 낮은 일치
- 일부 환자에서 3 consensus cluster가 더 이상 명확한 metastasis signature activity 분리 안 됨 → 확신 있는 MPC cluster 할당 불가
- 저자: "주요 생물학적 결론 유지" — 후보 MPC가 EMT, invasion, metastasis signature, ALCAM/VIM/SPARC 등 독립적 마커 발현 보여줌

**Reviewer 코멘트 (R2-5):**

**Concern — 가장 중요:**
- MPC 식별 자체가 MAGIC에 크게 의존 (median ARI 0.13).
- "주요 생물학적 결론 유지" 주장이 candidate MPC 수준에서는 타당하나, **세포 집단 정의의 robustness에 대한 우려는 남음**.
- 저자가 "candidate MPCs"로 표현 제한한 것은 부분적 완화.

**검토 필요:**
- Non-imputed 데이터에서 "3 consensus cluster가 더 이상 명확한 separation을 보이지 않아 confident MPC 할당 불가"라는 결과 → 이게 단순히 클러스터링 불안정성인지, 아니면 imputation 없이는 MPC/비MPC 구분 자체가 모호하다는 의미인지.
- 만약 후자라면, MPC가 real한 cell state인지에 대한 근본적 질문이 제기됨. 저자가 이 점을 어떻게 다루는지.

**핵심 질문:**
- "imputation이 없어도 주요 결론이 유지되는가"에 대한 저자의 기준이 무엇인지. MPC 라벨 자체의 일치(ARI 0.13)가 낮아도, "MPCs가 metastasis-associated transcriptional state를 보인다"는 결론이 유지된다는 건가? 그렇다면 그 결론의 근거는 imputed MPC 기준으로 도출된 생물학적 특성들 → circularity 가능성."""
}

for label, text in subsections:
    comment = results_comments.get(label, "*(세부 코멘트는 원문 확인 후 추가)*")
    send_to_slack(f"💬 Reviewer 코멘트 — {label}", comment)

# 5. Discussion
print("\n[5/7] Discussion")
send_to_slack("📄 Discussion (논문 원문)", discussion_text[:3000])

discussion_comment = """*🔍 Reviewer 코멘트 — Discussion*

**내용 요약 예상:**
- scMPC의 종합 정리: 단일세포 수준에서 MPC 식별, 진화/규제/TME 통합 관점
- "computationally inferred metastasis-associated transcriptional state" 프레임
- Limitation: CNV inference 한계, CellChat/pseudotime/공간 co-localization의 계산적 성격, PPI 네트워크의 단백질 수준 미검증, circularity 가능성, clinical association ≠ prediction, 샘플 크기 제한
- Future direction: functional validation, clinical translation

**Reviewer 코멘트:**

**잘 된 점 (예상):**
1. "computationally inferred metastasis-associated transcriptional state" framing — R1-1, R2-7에서 반복 요청된 핵심. Discussion에서 이 톤을 유지하는지.
2. Limitation 섹션에서 (1) CNV inference, (2) CellChat/pseudotime/공간, (3) PPI 네트워크, (4) circularity, (5) clinical association ≠ prediction, (6) 샘플 크기 등 주요 한계를 정직하게 다루는지.
3. "future experimental studies"로 마무리 — 가설 생성 수준임을 재확인.

**확인 필요:**
- "predicts", "validates", "drives", "remodels" 등 definitive/causal language가 Discussion에서 완전히 제거되었는지 (R1-1, R2-7).
- Limitation이 형식적으로 나열되는 데 그치지 않고, 각 한계가 결과의 해석에 어떻게 영향을 미치는지 구체적으로 논의하는지.
- Clinical association 주장(METABRIC HR=1.17)이 "association" 수준임을 Discussion에서 명확히 reiterate 하는지.

**종합 평가:**
- Discussion이 "our findings provide a systems-level view of transcriptomic features associated with metastatic progression" 정도의 톤으로 정리된다면 acceptable.
- "our work provides comprehensive view"로 요약하면서도 "these findings should be interpreted as identifying a computationally inferred...rather than providing direct functional evidence"라는 문구가 Discussion 어딘가에 있는지 확인. 이 한 문장이 논문의 해석 프레임 전체를 규정.

**최종 Reviewer 종합:**
이 논문은 computational framework로서 상당한 thoroughness를 갖추고 있으며, reviewer 지적에 대해 대체로 성실하게 대응함. 다만 다음에 유의:
1. RGS 선택 위양성 — 미해결
2. GSE44408 dual role — "threshold calibration"으로 명시했으나 완전한 독립 검증은 아님
3. MAGIC 의존성 — median ARI 0.13 → 세포 집단 정의의 robustness 우려
4. 동시 회귀 ARI 0.21 → MPC- canonical program 관계 해석에 주의 필요

현재의 "clinical association" framing 안에서는 acceptable 수준이나, prediction/utility 주장으로 확장하려면 추가 검증 필요."""

send_to_slack("💬 Reviewer 코멘트 — Discussion", discussion_comment)

print("\n" + "="*60)
print("모든 섹션 전송 완료")
print("="*60)
