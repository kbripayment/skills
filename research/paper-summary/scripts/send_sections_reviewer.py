#!/usr/bin/env python3
"""PDF 본문에서 섹션별 원문 + reviewer 의견 Slack 전송 (줄번호 제거)."""
import re
from pymupdf import open as fitz_open
from slack_sdk.web import WebClient

PDF_PATH = "C:/Users/user/.hermes/desktop-attachments/JTRM-D-26-00308_R2_reviewer.pdf"
env_path = "C:/Users/user/AppData/Local/hermes/.env"

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

doc = fitz_open(PDF_PATH)
pages = [doc[i].get_text() for i in range(13, 51)]
doc.close()
full = "\n".join(pages)

# 줄번호 제거: "\n  123  \n" 패턴 → 공백
def clean_lines(text):
    # 단독 줄번호(공백으로 둘러싸인 1~4자리 숫자)만 제거
    return re.sub(r'\n\s*\d{1,4}\s*\n', '\n', text)

# 섹션 경계 찾기
abs_pos = full.find("Background:")
methods_pos = full.find("Methods", abs_pos + 3500)
results_pos = full.find("Results", methods_pos + 100) if methods_pos != -1 else -1
disc_pos = full.find("Discussion", results_pos + 100) if results_pos != -1 else -1
ref_pos = full.find("References", disc_pos + 100) if disc_pos != -1 else -1

print(f"섹션 경계: Abs={abs_pos}, Methods={methods_pos}, Results={results_pos}, Discussion={disc_pos}, References={ref_pos}")

# 섹션별 추출
sections = {
    "Introduction": full[abs_pos+3500:methods_pos] if methods_pos != -1 else full[abs_pos+3500:abs_pos+5000],
    "Methods": full[methods_pos:results_pos] if methods_pos != -1 and results_pos != -1 else "",
    "Results": full[results_pos:disc_pos] if results_pos != -1 and disc_pos != -1 else "",
    "Discussion": full[disc_pos:ref_pos] if disc_pos != -1 and ref_pos != -1 else full[disc_pos:disc_pos+3000] if disc_pos != -1 else "",
}

# 줄번호 제거
for k in sections:
    sections[k] = clean_lines(sections[k])

c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2300

def send(label, text):
    if not text.strip():
        print(f"⚠️ [{label}] 빈 텍스트")
        return
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"✅ [{label}] → ts={resp['ts']} ({len(msg)} chars)")
        except Exception as e:
            print(f"❌ [{label}] {e}")
        return
    
    # 분할 전송
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    cur_lbl = label
    buf = ""
    for p in paras:
        trial = f"*{cur_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX and buf:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
                print(f"✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
            except Exception as e:
                print(f"❌ [{cur_lbl}] {e}")
            buf = p
            cur_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
        except Exception as e:
            print(f"❌ [{cur_lbl}] {e}")

print("\n=== 전송 시작 ===")

# ── Introduction ──
intro = sections.get("Introduction", "")
print(f"\n[1] Introduction: {len(intro)} chars")
send("📄 Introduction (논문 원문)", intro[:3000])

intro_reviewer = """*🔍 Reviewer 관점 코멘트 — Introduction*

**잘 된 점:**
1. EMT/pEMT 단일 서술에서 "spectrum of highly plastic cell states"로 패러다임 전환을 명시 → 최신 문헌(9,10,11) 인용 적절.
2. bulk 한계 → scRNA-seq + bulk 통합 프레임워크(scMPC)로 극복한다는 논리가 선명.
3. 26명 paired primary-LN metastasis 코호트라는 데이터 강점을 초반부터 강조.

**Reviewer로서 확인할 점:**
- "metastasis-initiating cells (MICs)" vs 본 연구 "MPC" 개념 관계 — Introduction에서 두 용어 관계(동일/차이/포함)를 더 명확히 하면 좋겠다. MICs는 일반적 개념, MPC는 본 프레임워크로 식별된 세포로 구분되는지.
- "actively remodel the TME" 표현(73-75라인)이 R1-1에서 지적된 과잉 서술 패턴. Introduction에서도 인과적 표현을 조금 더 cautiously 쓸 여지 있음. → 다만 이는 배경 문헌 리뷰이므로acceptable할 수 있음.

**주장 강도 평가:**
- Introduction의 주장은 대체로 background review 수준이라 수용 가능. "providing insights into the molecular programs associated with metastatic competence"는 적절.
- "future functional investigation"이라는 표현도 가설 생성 수준임을 잘 나타냄."""

send("💬 Reviewer 코멘트 — Introduction", intro_reviewer)

# ── Methods ──
methods = sections.get("Methods", "")
print(f"\n[2] Methods: {len(methods)} chars")
send("📄 Methods (논문 원문)", methods[:3000])

methods_reviewer = """*🔍 Reviewer 관점 코멘트 — Methods*

Methods 섹션은 일단 원문을 받아보고, 구체적인 코멘트는 해당 subsection을 리뷰하면서 추가로 드리겠습니다. 전반적인 인상만 먼저 공유드리면:

1. scMPC 프레임워크 설명: transfer-learning 접근법, bulk matched primary-metastasis 데이터에서 gene signature 추출하여 scRNA-seq 개별 세포에 적용하는 논리 — 재현성 있게 기술되어 있는지 확인 필요.

2. 세포 클러스터링 앙상블 방법(k-means + hierarchical consensus): 파라미터 선택 기준, cluster 수 결정 방법, stability 평가 방법이 명확히 제시되어야 함.

3. CNV 추론(inferCNV): 방법론적 한계(해상도, 위양성 등)가 Methods에 명시되어 있는지. R1-1B에서도 지적됐듯이 clonal origin 추론에 CNV만 쓰는 건 제한적.

4. CellChat, 공간 전사체 분석: 예측 기반 방법임을 Methods 수준에서 명시.

5. 통계 방법: permutation test, bootstrap, FDR 보정 등 — 세부 사항이 Methods에 충분히 기술되어 있는지.

*📌 Methods는 본문(Figures + Results)과 함께 읽어야 정확한 리뷰가 가능해서, 일단 원문만 먼저 보내드리고 각 Figure/Result 리뷰할 때 코멘트를 덧붙이겠습니다.*"""

send("💬 Reviewer 코멘트 — Methods", methods_reviewer)

# ── Results (Figure별 분할) ──
results = sections.get("Results", "")
print(f"\n[3] Results: {len(results)} chars")

# Results 내 Figure subsection 찾기
fig_markers = [
    ("Figure 1: Identification of metastasis-potential cells in primary breast Tumors using scMPC",
     ["Identification of metastasis-potential cells in primary breast"]),
    ("Figure 2: MPCs exhibit metastasis-associated transcriptional programs across multiple biological dimensions",
     ["MPCs exhibit metastasis-associated transcriptional programs"]),
    ("Figure 3: Genomic evolution, cell state dynamics, and regulatory programs of MPCs",
     ["Genomic evolution, cell state dynamics, and regulatory programs"]),
    ("Figure 4: MPCs are predicted to engage specific TME programs",
     ["MPCs are predicted to engage specific TME programs"]),
    ("Figure 5: Derivation and validation of an MPC-associated gene signature",
     ["Derivation and validation of an MPC-associated gene signature"]),
]

# Supplementary Figures
sup_markers = [
    ("Supplementary 분석: RGS permutation null (Supp. Fig. 3 관련)",
     ["To evaluate whether the retained RGSs showed"]),
    ("Supplementary 분석: MPC 식별 안정성 / 회귀 민감도 (Supp. Fig. 10 관련)",
     ["MPC identification was then repeated and compared"]),
    ("Supplementary 분석: 방법 비교 (Supp. Fig. 14 관련)",
     ["Consistent method-specific differences were also observed"]),
    ("Supplementary 분석: CytoTRACE2 (Supp. Fig. 12 관련)",
     ["Consistently, MPCs showed significantly elevated cellular plasticity"]),
    ("Supplementary 분석: MAGIC imputation 영향 (Supp. Fig. 13 관련)",
     ["To evaluate the impact of MAGIC imputation"]),
]

all_submarkers = fig_markers + sup_markers

# 각 subsection 위치 찾기
subsections = []
for label, kws in all_submarkers:
    for kw in kws:
        p = results.find(kw)
        if p != -1:
            subsections.append((p, label, kw))
            break

subsections.sort(key=lambda x: x[0])

# subsection 분할
chunks = []
for i, (pos, label, kw) in enumerate(subsections):
    start = pos
    end = subsections[i+1][0] if i+1 < len(subsections) else len(results)
    txt = clean_lines(results[start:end])
    if txt.strip():
        chunks.append((label, txt))

if not chunks:
    chunks = [("Results (전체)", clean_lines(results))]

print(f"  → {len(chunks)}개 subsection 분할:")
for lbl, t in chunks:
    print(f"    [{lbl}] {len(t)} chars")

for i, (label, text) in enumerate(chunks):
    print(f"\n  [Results/{i+1}] {label}: {len(text)} chars")
    
    # 원문 전송
    send(f"📄 Results — {label}", text[:3000])
    
    # reviewer 코멘트
    if "Figure 1" in label:
        comment = """*🔍 Reviewer 코멘트 — Figure 1 (scMPC overview + MPC 식별)*

**핵심 내용 예상:** scMPC 프레임워크 개요 + 26명 환자 scRNA-seq 데이터에서 MPC 식별 결과.

**Preview 코멘트:**
- scMPC가 각 환자별로 MPC를 식별했는지, 전체 환자에서의 일관성(residual/robustness)이 핵심.
- 환자별 MPC 비율의 분포, 식별 기준의 투명성(예: ensemble clustering의 threshold)이 중요.
- "MPCs emerged along distinct patient-specific evolutionary trajectories"라는 Results 첫 문장 — 이미 patient-specific vs general 구분 이슈가 R1에서 제기된 부분. Figure 1에서 이 duality를 어떻게 시각화했는지가 관건.

*원문을 받아서 세부 검토 후 추가 코멘트 드리겠습니다.*"""
    elif "Figure 2" in label:
        comment = """*🔍 Reviewer 코멘트 — Figure 2 (MPCs의 전사체적 특성)*

**핵심 내용 예상:** MPC vs NPC 비교 — EMT, invasion, metastasis signature, 세포 가소성(plasticity), 줄기세포 마커 등.

**Preview 코멘트:**
- R1-2(circularity): MPC 식별에 사용된 22개 M_signatures로 validation 하면 순환성 문제. 저자들은 ALCAM/VIM/SPARC를 독립 마커로 분리했고, SOX9/NEAT1/CCL5는 supportive로만 제시 → 이 구분이 Figure 2에서 잘 보이는지 확인.
- 세포 가소성(CytoTRACE2): 13명 중 4명에서만 유의 → 이 heterogeneity가 Figure 2에 어떻게 표현되는지.
- "MPCs exhibit pronounced metastatic capacity" 같은 표현은 앞서 R1이 "metastasis-associated transcriptional programs"로 순화 요청 → Figure 2 제목/legend에서 언어 완화가 반영되었는지.

*원문 확인 후 세부 코멘트 추가.*"""
    elif "Figure 3" in label:
        comment = """*🔍 Reviewer 코멘트 — Figure 3 (게놈 진화, 세포 상태 역학, 조절 프로그램)*

**핵심 내용 예상:** CNV 기반 clonal architecture, pseudotime trajectory (Monocle2 + scTour), TF-target regulatory network (GRNBoost2), AP-1/KLF6/CEBPD 등.

**Preview 코멘트 (R1-1B 관련):**
- "MPCs originated from multiple subclones", "17q gain likely drove metastasis" 같은 표현 → 저자는 "consistent with" 수준으로 완화. Figure 3에서 여전히 방어적으로 보이는 주장이 없는지 확인.
- Pseudotime: Monocle2 primary, scTour sensitivity. Trajectory 해석이 "inferred transcriptional progression"임을 명확히 했는지.
- Regulatory network: GRNBoost2 기반. mRNA→PPI 네트워크와의 관계, R1-1C에서 지적된 "mRNA-derived, PPI-prioritized candidate signature" 프레임이 규제 네트워크 해석에도 적용되는지.

*원문 확인 후 세부 코멘트 추가.*"""
    elif "Figure 4" in label:
        comment = """*🔍 Reviewer 코멘트 — Figure 4 (MPCs-TME 상호작용)*

**핵심 내용 예상:** CellChat 기반 ligand-receptor 상호작용 예측, 공간 전사체 co-localization, ECM-receptor / cell-cell contact / secreted signaling 분류.

**Preview 코멘트 (R1-1A 관련):**
- CellChat 예측 → "predicted ligand-receptor interactions"로 언어 완화되었는지.
- VEGFA-VEGFR1 (patient 180-3), C3-C3AR1 (patient 195-1), CXCL12 (patient 161-5) 등 단일 환자 관찰 → 일반화된 "shape a pro-metastatic ecosystem" 주장으로 확장하지 않았는지.
- "more than half (51%) belonging to the ECM-receptor category" 정량화 명확해야 함 (Minor h에서 지적됨, 저자 수용).
- 공간 co-localization: 전사체 수준 co-localization이 물리적/기능적 상호작용을 입증하지는 않음. 이 한계가 Figure 4에서 명확히 드러나는지.

*원문 확인 후 세부 코멘트 추가.*"""
    elif "Figure 5" in label:
        comment = """*🔍 Reviewer 코멘트 — Figure 5 (MPC 시그니처 도출 및 검증)*

**핵심 내용 예상:** PPI 네트워크(STRING) → 22개 유전자 시그니처 도출, MetMap500, METABRIC 등에서 검증, ROC/AUC, Cox 분석.

**Preview 코멘트:**
- R1-1C: mRNA→PPI 네트워크. "mRNA-derived, PPI-prioritized candidate signature"로 명시했는지. STRING v12.0, confidence ≥0.700 등 파라미터 투명해야 함 (Minor f에서 지적됨, 저자 수용).
- R1-3: "predictor" 용어 삭제 → "Derivation and validation of an MPC-associated gene signature"으로 제목 변경. 임상 주장을 "association"으로 제한.
- METABRIC Cox: HR=1.17 (1.04-1.32, P=0.011). TCGA-BRCA 제거됨 (조정 후 유의하지 않음).
- R1-4, R2-1: RGS 선택의 union-based top 10% 위양성 → 순열 분석으로 "선택된 RGS"의 무작위 대비 유의성은 확인했으나 선택 과정 자체의 위양성률은 미해결.
- MetMap500 해석: weakly metastatic lines에서 highest score → "early acquisition" 가설. 저자의 balanced interpretation 확인.

*원문 확인 후 세부 코멘트 추가.*"""
    elif "permutation" in label.lower() or "RGS" in label:
        comment = """*🔍 Reviewer 코멘트 — RGS permutation null 분석 (Supp. Fig. 3)*

**R1-4 / R2-1 대응:**
- 100만 개 RGS 중 union-based top 10% 선택 → 우연 포함 가능성.
- 저자 대응: 선택된 RGS에 대해 500회 label permutation, empirical P + BH 보정.
- 한계: **선택 과정 자체의 위양성률 control은 아님.** 선택된 RGS가 무작위보다 나은지만 평가.
- 저자: 작은 데이터셋은 enrichment 약함 / 하나도 유의하지 않음 → power issue로 해석. "선별 기준 추가는 underpowered dataset 정보 손실 우려"라고 방어.

**Reviewer로서:**
- 이 접근은 RGS 선택의 정당성을 완전히 증명하지는 않지만, 선택된 RGS가 의미 없는 noise는 아니라는 evidence는 됨.
- R2-1에서 동일 지적이 반복됨 → 저자가 "permutation filtering은 scope 초과"라는 입장 고수. 이 부분이 납득 가능한지 논의 필요."""

    elif "stability" in label.lower() or "반복" in label:
        comment = """*🔍 Reviewer 코멘트 — MPC 식별 안정성 / 회귀 민감도 (Supp. Fig. 10)*

**R1-2, R2-4 관련:**
- Random seed 변경 → ARI/NMI/Jaccard 모두 1.00 (완전 일치) → robust.
- Cluster 수 범위 확장(12) → median ARI 0.98, NMI 0.95, Jaccard 0.99 → robust.
- 계층적 클러스터링 linkage: Ward.D → ARI 0.89, average → ARI 0.39 (민감도 높음) → linkage 선택이 중요.
- Gene retention threshold: top 30 → ARI 0.79, top 70 → ARI 0.95.
- 회귀 민감도: cell cycle / hypoxia / stress response 개별 제거 → MPC labels 대체로 유지. 동시 제거 → ARI 0.21 급감.

**Concern:**
- 동시 회귀 시 ARI 0.21 → 저자는 "overcorrection, biologically intertwined"로 해석. Reviewer 관점에서는 이 해석이 순환성 지적을 완전히 해소하지는 않음. MPC 정의가 이들 프로그램과 상당히 얽혀있다는 신호일 수 있음.

*원문 확인 후 세부 코멘트 추가.*"""
    elif "method comparison" in label.lower() or "Scissor" in label:
        comment = """*🔍 Reviewer 코멘트 — 방법 비교 (Supp. Fig. 14)*

**Minor 6 대응:**
- Scissor 3/13 환자 vs scMPC 13/13 → scMPC 우위.
- scAB 13/13, scPAS 11/13, LP_SGL 7/13, SCIPIC 10/13.
- Scissor "비슷한 결과" 표현 삭제 → 구체적 수치 제시.

**Reviewer 관점:**
- 방법별 patient coverage 차이 명확해짐. 다만 scMPC가 13/13이라는 게 "더 좋다"는 주장의 근거는 환자 coverage만이 아니라 cell-level 품질(EMT/침습/전이 signature 점수 등)도 필요.
- Scissor가 3/13만 식별한 이유가 방법론적 한계(예: bulk reference 품질, phenotype 정의)인지, 아니면 scMPC보다 보수적이어서인지도 고려."""

    elif "CytoTRACE" in label:
        comment = """*🔍 Reviewer 코멘트 — CytoTRACE2 (Supp. Fig. 12)*

**Minor g 대응:**
- 13명 중 4명(161_3, 161_5, 180_3, 180_5)에서만 MPC가 NPC보다 유의하게 높은 CytoTRACE2 점수.
- 저자: 더 이상 "일관된 plasticity 증거"로 기술하지 않고 "patient-dependent support"로 표현.

**Reviewer 관점:**
- CytoTRACE가 developmental potency 측정 → 암세포 전이 가소성과 반드시 일치하지는 않음. 4/13만 유의한 건 놀라운 일 아님.
- 이 이질성이 MPC 정의의 robustness에 대해 시사하는 바: 일부 환자에서 MPC가 진정한 high-plasticity state가 아닐 수 있음. 저자 해석은 조심스럽고 적절."""

    elif "MAGIC" in label:
        comment = """*🔍 Reviewer 코멘트 — MAGIC imputation 영향 (Supp. Fig. 13)*

**R2-5 대응:**
- Non-imputed 데이터로 파이프라인 재실행 → median ARI 0.13, NMI 0.19, Jaccard 0.52.
- 일부 환자(167_8, 180_5) 거의 일치, 다른 환자는 낮은 일치.
- 일부 환자에서 3 consensus cluster가 더 이상 명확한 metastasis signature activity 분리 안 보임 → 확신 있는 MPC cluster 할당 불가.

**Concern:**
- MPC라는 세포 집단 식별 자체가 imputation에 크게 의존. 저자의 "주요 생물학적 결론 유지" 주장은 후보 MPC 수준에서는 타당하나, 세포 집단 정의의 robustness에 대해서는 남는 우려.
- 저자는 "candidate MPCs"로 표현 제한 → 부분적 완화. Slack에서 "imputation 없이도 주요 결론이 유지되는가"의 기준 논의 필요."""

    else:
        comment = "*(세부 코멘트는 원문 확인 후 추가)*"

    send(f"💬 Reviewer 코멘트 — {label}", comment)

# ── Discussion ──
discussion = sections.get("Discussion", "")
print(f"\n[4] Discussion: {len(discussion)} chars")
send("📄 Discussion (논문 원문)", discussion[:3000])

discussion_reviewer = """*🔍 Reviewer 관점 코멘트 — Discussion*

Discussion은 논문의 interpretive layer라서 특히 주의 깊게 봐야 합니다. 원문 받아보고 세부 코멘트 드리겠지만, Preview로:

1. "computationally inferred metastasis-associated transcriptional state"라는 프레임을 Discussion에서 얼마나 일관되게 유지하는지 — R1-1, R2-7에서 반복적으로 요청된 부분.

2. Limitation 섹션에서 다음을 명확히 다루는지:
   - scRNA-seq 기반 CNV inference의 한계 (R1-1B)
   - CellChat/pseudotime/공간 co-localization이 실험적 검증 아님 (R1-1A)
   - mRNA→PPI 네트워크의 단백질 수준 미검증 (R1-1C)
   - MPC 정의의 circularity 가능성 (R1-2)
   - clinical association ≠ prediction (R1-3)
   - 26명 환자 scRNA-seq의 샘플 크기 제한

3. "future functional investigation" / "future experimental studies"로 마무리하는 톤 — 적절한 수준인지.

*원문 확인 후 세부 코멘트 추가.*"""

send("💬 Reviewer 코멘트 — Discussion", discussion_reviewer)

print("\n=== 전송 완료 ===")
