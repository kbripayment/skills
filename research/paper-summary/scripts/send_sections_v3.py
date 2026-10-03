#!/usr/bin/env python3
"""PDF 본문에서 섹션 경계를 정확히 찾아 Slack에 전송 (원문 + Reviewer 코멘트)."""
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

# PDF 본문(p.14~51) 추출 후 줄번호 제거
doc = fitz_open(PDF_PATH)
pages_text = [doc[i].get_text() for i in range(13, 51)]
doc.close()

def remove_line_numbers(text):
    out = []
    for line in text.split('\n'):
        s = line.strip()
        if s.isdigit() and 1 <= int(s) <= 9999:
            continue
        out.append(line)
    cleaned = '\n'.join(out)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

clean_text = remove_line_numbers("\n".join(pages_text))

# ── 섹션 경계 찾기 (Methods 내 "Discussion" 단어 회피) ──
# Abstract
abs_pos = clean_text.find("Background:")

# Methods: Abstract 이후 첫 "Methods" (Methods 본문 내 "Discussion" 등이 섞여도 방법이 첫 등장)
methods_start = None
for m in re.finditer(r'\bMethods\b', clean_text):
    if m.start() > abs_pos + 3000:
        ctx = clean_text[max(0,m.start()-80):m.start()+80]
        if any(x in ctx.lower() for x in ['see methods', 'in the methods', 'methods section']):
            continue
        methods_start = m.start()
        break

# Results: Methods 이후 첫 "Results"
results_start = None
for m in re.finditer(r'\bResults\b', clean_text):
    if m.start() > (methods_start + 1000 if methods_start else 0):
        ctx = clean_text[max(0,m.start()-80):m.start()+80]
        if any(x in ctx.lower() for x in ['see results', 'in the results', 'results section']):
            continue
        results_start = m.start()
        break

# Discussion: Results 이후 첫 "Discussion" (Methods 내 "Discussion" 회피 위해 Results 이후만 검색)
discussion_start = None
if results_start:
    after_results = clean_text[results_start:]
    for m in re.finditer(r'\bDiscussion\b', after_results):
        pos = results_start + m.start()
        ctx = clean_text[max(0,pos-80):pos+80]
        # Methods 안에서 "Discussion"이 쓰이는 패턴 제외 (e.g. "see Discussion", "in the Discussion")
        ctx_low = ctx.lower()
        if any(x in ctx_low for x in ['see discussion', 'in the discussion', 'the discussion section',
                                        'discussion. we', 'discussion, we']):
            continue
        # Results 본문 끝나고 Discussion 시작되는 지점
        # "Discussion" 앞에 문장 종료(마침표 + 공백 + "Discussion")
        before = clean_text[pos-30:pos]
        if re.search(r'\.\s+Discussion\s', before + 'Discussion '):
            discussion_start = pos
            break
        # 또는 "Discussion" 앞이 빈 줄
        if re.search(r'\n\s*Discussion\s', before + 'Discussion '):
            discussion_start = pos
            break

# References: Discussion 이후 첫 "References" (Not applicable 직전)
references_start = None
if discussion_start:
    after_disc = clean_text[discussion_start:]
    for m in re.finditer(r'\bReferences\b', after_disc):
        pos = discussion_start + m.start()
        ctx = clean_text[max(0,pos-40):pos+60]
        if 'Not applicable' in ctx:
            continue
        references_start = pos
        break

print(f"섹션 위치:")
print(f"  Abstract: {abs_pos}")
print(f"  Methods: {methods_start}")
print(f"  Results: {results_start}")
print(f"  Discussion: {discussion_start}")
print(f"  References: {references_start}")

# 섹션별 텍스트
intro_text = ""
if abs_pos and methods_start:
    intro_text = clean_text[abs_pos+3500:methods_start]
elif abs_pos:
    intro_text = clean_text[abs_pos+3500:results_start] if results_start else clean_text[abs_pos+3500:]

methods_text = ""
if methods_start and results_start:
    methods_text = clean_text[methods_start:results_start]
elif methods_start:
    methods_text = clean_text[methods_start:discussion_start] if discussion_start else clean_text[methods_start:]

results_text = ""
if results_start:
    end = discussion_start if discussion_start else (references_start if references_start else len(clean_text))
    results_text = clean_text[results_start:end]

discussion_text = ""
if discussion_start:
    end = references_start if references_start else len(clean_text)
    discussion_text = clean_text[discussion_start:end]

print(f"\n섹션 길이: Intro={len(intro_text)}, Methods={len(methods_text)}, Results={len(results_text)}, Discussion={len(discussion_text)}")

# Results 시작/끝 확인
print(f"\nResults 첫 300자:\n{results_text[:300]}")
print(f"\nResults 끝 300자:\n{results_text[-300:]}")
print(f"\nDiscussion 첫 300자:\n{discussion_text[:300]}")
print(f"Discussion 끝 300자:\n{discussion_text[-300:]}")

# ── Results를 Figure subsection으로 분할 ──
subsection_markers = [
    ("Figure 1: Identification of metastasis-potential cells in primary breast Tumors using scMPC",
     ["Identification of metastasis-potential cells in primary breast"]),
    ("Supplementary Figure 3: RGS permutation null analysis",
     ["To evaluate whether the retained RGSs showed"]),
    ("Figure 2: MPCs exhibit metastasis-associated transcriptional programs across multiple biological dimensions",
     ["MPCs exhibit metastasis-associated transcriptional programs"]),
    ("Supplementary Figure 14: Method comparison",
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

subsections_with_pos = []
for label, keywords in subsection_markers:
    for kw in keywords:
        pos = results_text.find(kw)
        if pos != -1:
            subsections_with_pos.append((pos, label))
            break

subsections_with_pos.sort(key=lambda x: x[0])
subsections = []
for i, (pos, label) in enumerate(subsections_with_pos):
    start = pos
    end = subsections_with_pos[i+1][0] if i+1 < len(subsections_with_pos) else len(results_text)
    txt = results_text[start:end].strip()
    if txt:
        subsections.append((label, txt))

if not subsections:
    subsections = [("Results (전체)", results_text)]

print(f"\nResults → {len(subsections)}개 subsection:")
for label, txt in subsections:
    print(f"  [{label}] {len(txt)} chars")

# ── Slack 전송 ──
c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"
MAX = 2300

def send(label, text):
    if not text.strip():
        print(f"  ⚠️ [{label}] 빈 텍스트")
        return
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= MAX:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"  ✅ [{label}] → ts={resp['ts']} ({len(msg)} chars)")
        except Exception as e:
            print(f"  ❌ [{label}] {e}")
        return
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    cur_lbl = label
    buf = ""
    for p in paras:
        trial = f"*{cur_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > MAX and buf:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
                print(f"  ✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
            except Exception as e:
                print(f"  ❌ [{cur_lbl}] {e}")
            buf = p
            cur_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"  ✅ [{cur_lbl}] → ts={resp['ts']} ({len(buf)} chars)")
        except Exception as e:
            print(f"  ❌ [{cur_lbl}] {e}")

print("\n" + "="*60)
print("SLACK 전송 시작 (원문 + Reviewer 코멘트)")
print("="*60)

# Abstract
print("\n[1/5] Abstract")
abstract = clean_text[abs_pos:abs_pos+3500] if abs_pos else clean_text[:3500]
send("📄 Abstract (논문 원문)", abstract[:3000])

abstract_comment = """*🔍 Reviewer 코멘트 — Abstract*

**요약:**
- scMPC: bulk matched primary-metastasis transcriptomes + scRNA-seq → 환자별 MPC 식별
- 26명 림프절 전이 유방암 환자 scRNA-seq
- MPC: 환자 특이적 진화 궤적, 중간엽 가소성 상태, AP-1/KLF6/CEBPD 조절, 공간적 TME 상호작용
- MPC 유전자 시그니처 → 조기 재발 연관

**Reviewer 관점:**
- Abstract는 주로 hypothesis-generating 프레임으로 잘 정리됨. "identify", "characterize", "provide insights" 정도 표현 수준.
- "MPCs shape a pro-metastatic tumor ecosystem" 류 표현이 있다면 R1-1에서 지적된 과잉 서술이나, Abstract에서는 압축 때문에 들어갈 수 있음.
- "mechanism" 단어 사용 시 계산적 예측임을 암시하는지 확인 필요.

**주장 강도 평가:** Abstract는 전반적으로 acceptable 수준. 인과적 과잉 표현이 있다면 R1 지적에 따라 수정된 버전 반영 여부 확인."""

send("💬 Reviewer 코멘트 — Abstract", abstract_comment)

# Introduction
print("\n[2/5] Introduction")
send("📄 Introduction (논문 원문)", intro_text[:3000])

introduction_comment = """*🔍 Reviewer 코멘트 — Introduction*

**요약:**
- 림프절 전이 중요성 → 전이 가능 세포 기전 규명 필요
- EMT/pEMT 한계 → "spectrum of highly plastic cell states"로 패러다임 확장
- MICs 개념, TME 재구성(R1-1A 지적 맥락)
- bulk 한계 → scRNA-seq + bulk 통합(scMPC)으로 극복
- 26명 paired primary-LN metastasis 데이터로 MPC 식별 + 특성 규명

**Reviewer 관점 (찬성):**
- 배경 서술이 최신 문헌 반영, 논리 전개 매끄러움.
- EMT 단일 패러다임 → plasticity spectrum 전환 설득력 있음.
- "future functional investigation" 표현 — 발견을 가설 생성 수준으로 위치 (Good).

**지적 사항:**
1. MICs vs MPC 용어 관계 — Introduction에서 구분 명확하지 않음. MICs는 일반 개념, MPC는 scMPC로 식별된 구체적 세포군으로 구분되는지 정리 필요.
2. "actively remodel the TME" 표현(R1-1A 지적 맥락) — 서론 배경 문헌 리뷰 수준이므로 용인될 여지 있으나, "associated with", "recruit/repurpose stromal components" 정도로 완화 가능.
3. "mechanisms underlying" — 계산적 연구에서 mechanism 주장할 때 한계 명확화 필요.

**종합:** Introduction 대체로 잘 쓰였고 주장 강도도 acceptable. 언급된 2개 포인트 정리 시 더 견고."""

send("💬 Reviewer 코멘트 — Introduction", introduction_comment)

# Methods
print("\n[3/5] Methods")
send("📄 Methods (논문 원문)", methods_text[:3000])

methods_comment = """*🔍 Reviewer 코멘트 — Methods*

**요약:** scMPC 파이프라인 전체 기술 — bulk 처리, RGS 발견(100만 개, union-based top 10%), RRA 통합, scRNA-seq 처리(SCT 정규화, MAGIC 선택, 앙상블 클러스터링), CNV 추론, pseudotime(Monocle2+scTour), CellChat, GRNBoost2 규제 네트워크, STRING PPI → 22개 시그니처, METABRIC 임상 분석(censoring-aware Cox), permutation/bootstrap/CFA 등 검증.

**잘 된 점:**
- 파이프라인 단계별 투명성 양호. RGS 발견 절차, RRA 통합, signature optimization 근거 및 민감도 분석(top 30/50/70).
- 임상 분석 Methods: censoring-aware approach, multivariable 조정 변수, NPI sensitivity model 구체적.
- Supplementary 추가 분석(부트스트랩 CI, permutation, 회귀 민감도, MAGIC 비교, 방법 비교)이 Methods에서 적절히 언급됨.

**보완 필요:**

1. **RGS 선택 위양성률 (R2-1, R1-4)**
   - Methods에 union-based top 10% 절차 기술돼 있으나 FPR formal control 없음.
   - 저자는 supplementary에서 permutation null을 "민감도 평가"로 추가. Methods 자체에서 "RGS selection was performed using a union-based criterion, and retained sets were subsequently evaluated against a permutation-derived empirical null (Supp. Fig. 3)" 정도로 기술하면 더 투명.

2. **GSE44408 dual role (R2-2)**
   - Methods 3.2: "GSE44408을 threshold-tuning dataset으로 사용" 명시 → 개선됨.
   - 그러나 discovery 단계에서도 GSE44408이 gene ranking에 기여 → 완전히 독립적이진 않음.
   - "threshold calibration"임을 강조하되 discovery 기여도도 명시하면 더 투명.

3. **MAGIC imputation 의존성 (R2-5)**
   - Methods에 "MAGIC imputation was applied to enhance signal recovery" 기술 예상.
   - 이 선택이 MPC 식별에 결정적 영향(median ARI 0.13 without MAGIC)을 미친다는 결과가 supplementary. Methods 자체에서도 imputation 선택 근거와 민감도 언급 검토 필요.

4. **inferCNV 한계 (R1-1B)**
   - Methods에 inferCNV 사용 기술. CNV inference가 clonal origin 주장에 어떻게 연결되는지의 방법론적 한계 설명이 Methods에 있는지 확인 필요.

5. **PPI 네트워크 파라미터 (Minor f)**
   - Methods에 STRING v12.0, confidence ≥0.700, cytoHubba 12개 알고리즘, ≥4 알고리즘에서 공통 → 22개 명시됨(저자 수용). Good.

6. **부트스트랩 CI (Minor i)**
   - Methods에 "1,000 bootstrap resamples, percentile CI" 명시됨(저자 수용). Good.

**종합:** Methods는 전반적 기술적 재현성 갖춘 수준. RGS 선택 위양성, MAGIC 의존성, GSE44408 dual role이 가장 중요한 methodological concern."""

send("💬 Reviewer 코멘트 — Methods", methods_comment)

# Results Figure별
print(f"\n[4/5] Results ({len(subsections)}개 subsection)")
for label, txt in subsections:
    print(f"\n  → {label}")
    send(f"📄 Results — {label}", txt[:3000])

# Figure별 reviewer 코멘트 정의
results_comments = {
    "Figure 1: Identification of metastasis-potential cells in primary breast Tumors using scMPC": """*🔍 Reviewer 코멘트 — Figure 1*

**내용 요약 예상:** scMPC 프레임워크 개요 + 26명 환자 scRNA-seq 데이터에서 환자별 MPC 식별 결과 + MPC 비율, 클러스터 분포, M_signature 활동 등.

**Reviewer 코멘트:**

**R1-2(circularity) 관점:**
- Figure 1에서 MPC 식별 결과가 EMT, invasion, metastasis score로 "검증"되는 패턴 있다면 circularity 지적 대상.
- 저자들이 ALCAM/VIM/SPARC를 독립 마커로 분리했는지, Figure 1에서 독립 검증 마커가 강조되는지 확인 필요.

**R1-1B(patient-specific vs general) 관점:**
- Figure 1이 "13개 primary tumors에서 MPC 식별"을 보여줌 → 환자 특이적 vs 공통 특징의 구분이 시각적으로도 드러나야 함.
- 저자 응답: "MPCs identified in all 13 patients" → scMPC가 전체 환자에서 작동한다는 주장. "universal" 증명 아니지만, 환자 간 이질성 속에서도 식별은 됨을 보여줌.

**심사 포인트:**
- MPC 식별의 신뢰도를 보여주는 evidence (stability, cluster quality)는 무엇인지.
- "distinct patient-specific evolutionary trajectories" 서술이 Figure 1에서 어떻게 뒷받침되는지. Patient별 세부 결과가 Figure 1에 포함되는지, 후속 Figure에서 나오는지.""",

    "Supplementary Figure 3: RGS permutation null analysis": """*🔍 Reviewer 코멘트 — RGS permutation null (Supp. Fig. 3)*

**내용 요약 예상:** 100만 개 RGS 중 union-based top 10% 선택된 RGS들 대상, 500회 label permutation → empirical null 분포, selected RGS들의 성능이 random보다 유의미하게 높은지 평가 (empirical P + BH 보정).

**Reviewer 코멘트 (R1-4, R2-1):**

**저자 대응 평가:**
- RGS 선택 **후** permutation 평가 → 선택 과정의 FPR control은 아님.
- "Retained RGSs generally exceeded random expectation" → 선택적 편향 후 평가에서 노이즈 아님을 보임.
- 작은 데이터셋은 유의하지 않음 → power issue로 해석. 저자는 "additional filtering은 underpowered dataset에 해롭다"고 방어.

**Reviewer 관점:**
- 이 접근의 한계 분명하나, 선택된 RGS가 전혀 근거 없는 noise는 아니라는 evidence로는 기능.
- 단, "permutation filtering을 추가적 선택 기준 삼지 않음"이라는 저자의 판단 → 예측 모델로 포지셔닝하려면 더 stringent control 필요했을 것. 현재 "clinical association" 프레임에서는 acceptable.

**핵심 질문:** permutation test에서 어떤 RGS가 살아남고 어떤 게 탈락하는지, 데이터셋별 차이가 있는지 → supplementary에 제대로 있는지.""",

    "Figure 2: MPCs exhibit metastasis-associated transcriptional programs across multiple biological dimensions": """*🔍 Reviewer 코멘트 — Figure 2*

**내용 요약 예상:** MPC vs NPC 비교: EMT, invasion, metastasis signature, 세포 가소성(plasticity), 줄기세포 마커(ALCAM, VIM, SPARC, SOX9, NEAT1, CCL5), high-plasticity cell state program, CytoTRACE2: 4/13 환자에서만 유의.

**Reviewer 코멘트:**

**R1-2(circularity) — 가장 핵심:**
- Figure 2에서 MPC "검증" 방식으로 EMT/침습/전이 score를 사용하는 부분 있다면 순환성 문제.
- 저자 수정: ALCAM/VIM/SPARC = 독립 마커(22개 M_signatures에 없음), SOX9/NEAT1/CCL5 = supportive only. 이 구분을 Figure 2에서 명확히 하는지 확인.
- "MPCs exhibit pronounced metastatic capacity"는 R1이 "metastasis-associated transcriptional programs"로 순화 요청 → Figure 2 제목/legend에서 반영 여부.

**R1-5(regression sensitivity) 연계:**
- Cell cycle, hypoxia, stress response 제거 후에도 MPC 특성 유지되는지 민감도 분석 결과 → Figure 2 관련 supplementary에 포함.
- 개별 제거 시 유지되나, 동시 제거 시 ARI 0.21로 하락 → Figure 2 해석 시 이 점 감안: MPC가 이들 프로그램과 완전히 독립적이지 않음.

**CytoTRACE2 (Minor g):**
- 13명 중 4명만 유의 → 저자: "patient-dependent support for increased developmental potential"으로 표현 조정. Good.
- CytoTRACE가 developmental potency 측정 → 암세포 전이 가소성과 직접 연결 제한적. 이 한계를 discussion/legend에서 인지하는지.""",

    "Supplementary Figure 14: Method comparison": """*🔍 Reviewer 코멘트 — 방법 비교 (Supp. Fig. 14)*

**내용 요약 예상:** Scissor: 3/13 환자에서만 phenotype-associated cells 식별. scAB: 13/13, scPAS: 11/13, LP_SGL: 7/13, SCIPIC: 10/13. scMPC: 13/13. 방법 간 overlap 분석.

**Reviewer 코멘트 (Minor 6):**

**저자 대응 평가:**
- "세 방법이 비슷한 결과를 보였다"는 원문의 과도한 일반화를 삭제 → 구체적 patient-level 결과 제시.
- Scissor 낮은 coverage(3/13) vs scMPC 13/13 → scMPC 장점으로 해석 가능하나 주의 필요.

**Reviewer 관점:**
- "환자에서 phenotype-associated cells 식별"만으로 방법의 우월성 주장하기엔 부족.
- Scissor coverage 낮은 이유: bulk reference 품질? phenotype 정의? 방법론적 한계?
- 방법 간 overlap 낮은 이유: 각 방법이 다른 transcriptional signal에 의존 → 이게 scMPC의 "독립성" 입증인지, 아니면 다른 기준일 뿐인지.

**주의점:**
- scMPC가 13/13이라고 "더 정확하다"는 보장 없음 — gold standard 없으므로 환자 coverage는 하나의 기준일 뿐.
- 이 section은 "scMPC가 다양한 complementary 방법과 비교하여 일관된 MPC-like 집단을 식별한다" 정도 framing이 적절.""",

    "Figure 3: Genomic evolution, cell state dynamics, and regulatory programs of MPCs": """*🔍 Reviewer 코멘트 — Figure 3*

**내용 요약 예상:** CNV 기반 clonal architecture(inferCNV), pseudotime trajectory(Monocle2+scTour), TF-target regulatory network(GRNBoost2), differential edge 분석, AP-1(FOS/JUN), KLF6, CEBPD 등 regulatory 프로그램.

**Reviewer 코멘트:**

**R1-1B — clonal origin 주장 (가장 중요):**
- "MPCs originated from multiple subclones" → "consistent with CNV-inferred monoclonal/polyclonal emergence"으로 완화되었는지.
- "17q gain likely drove metastasis" → "candidate genomic alterations associated with metastatic competence" 수준으로 완화되었는지.
- Figure 3에서 CNV 분석이 clonal origin의 **증거**처럼 제시되는지, "consistent with" 패턴으로 제시되는지.

**Pseudotime (R1-1B):**
- Monocle2 primary, scTour sensitivity check → "inferred transcriptional progression, not direct developmental history" framing.
- Trajectory 상 MPC 위치("early/late") 주장이 definitive 하게 제시되는지, "occupy transcriptional states ordered along inferred pseudotime" 수준인지.

**Regulatory network (R1-1C, R1-5):**
- GRNBoost2 기반 TF-target edge → mRNA 발현 기반 추론. 단백질 수준 검증 아님.
- R1-5에서 지적된 "95% CI" → "95% permutation-null interval"로 수정.
- 유의성: empirical P < 0.05 → BH FDR < 0.05 → 6 edges만 통과 (42 edges nominal). 보수적.
- Figure 3에서 regulatory edge들이 "validated regulatory interactions"처럼 제시되는지, "computationally inferred candidate interactions"로 제시되는지.

**핵심 question:** Figure 3의 narrative가 "evolutionary history를 재구성했다"는 인상을 주는지, "transcriptional dynamics와 regulatory programs의 연관성을 computational하게 탐색했다"는 인상을 주는지. 전자라면 R1 지적에 위배.""",

    "Figure 4: MPCs are predicted to engage specific TME programs": """*🔍 Reviewer 코멘트 — Figure 4*

**내용 요약 예상:** CellChat 기반 ligand-receptor 상호작용 예측, ECM-receptor(51%), cell-cell contact(26%), secreted signaling(23%), VEGFA-VEGFR1(pt 180-3), C3-C3AR1(pt 195-1), CXCL12(pt 161-5) 등, 공간 전사체 co-localization.

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

**종합:** Figure 4는 "예측된 상호작용의 landscape"를 보여주는 데 초점. "TME를 actively remodel한다"는 주장이 빠졌다면 적절한 수준의 결과 제시. 다만, 이러한 예측들이 "hypothesis-generating" 목적임을 figure legend와 discussion에서 반복적으로 명시하는지 확인.""",

    "Figure 5: Derivation and validation of an MPC-associated gene signature": """*🔍 Reviewer 코멘트 — Figure 5*

**내용 요약 예상:** MPC 시그니처 도출 과정(STRING PPI → 22개 유전자), MetMap500에서 weak/highly metastatic lines 비교, METABRIC ssGSEA + Cox 분석(HR=1.17, P=0.011), TCGA-BRCA 제거됨.

**Reviewer 코멘트:**

**R1-1C — mRNA→PPI (가장 중요):**
- "mRNA-derived, PPI-prioritized candidate signature"로 명시되었는지.
- STRING v12.0, confidence ≥0.700, cytoHubba 12개 알고리즘, ≥4 알고리즘에서 공통 → 22개. 파라미터 투명해짐 (Minor f, 저자 수용).
- 6개 유전자만 Human Protein Atlas 교차 참조 → 제한적. 이 한계 discussion에서 인지하는지.

**R1-3 — 임상 주장 (가장 중요):**
- "predictor", "independent predictor", "clinically actionable" → 모두 삭제됨. "Derivation and validation of an MPC-associated gene signature"으로 섹션 제목 변경.
- METABRIC Cox: HR=1.17(1.04-1.32, P=0.011), NPI-adjusted HR=1.16(1.03-1.31, P=0.015)
- TCGA-BRCA 분석 제거됨(조정 후 유의하지 않음). 어려운 결정이었으나 적절.
- "clinical association" ≠ predictive performance → 명확하게 구분됨.

**R1-4, R2-1 — RGS 선택:**
- Figure 5의 시그니처 도출은 RGS→RRA→22개 유전자. RGS 선택의 위양성 문제가 이 시그니처 신뢰도에 영향.
- Supplementary Fig 3의 permutation 분석에서 smallest dataset 유의하지 않음 → 시그니처 도출의 기반이 일부 약한 데이터셋 포함.

**MetMap500 (Minor d):**
- Weakly metastatic lines에서 highest score → "early acquisition" 가설.
- 저자 수정: "may capture transcriptional programs associated with early metastatic progression, although further functional studies are required... alternative biological explanations also possible" → balanced.

**부트스트랩 CI (Minor i):**
- Figures/Results에 AUC, balanced accuracy, precision, F1에 대한 95% bootstrap CI 포함(1,000 resamples, percentile method). Good.

**종합:** Figure 5는 가장 임상적으로 의미 있는 섹션. 그러나 주장 강도는 "clinical association" 수준으로 제한되어야 함. "predictive signature"라는 positioning은 현재 데이터로는 과장.""",

    "Supplementary Figure 10: MPC 식별 안정성 + 회귀 민감도 분석": """*🔍 Reviewer 코멘트 — MPC 식별 안정성 + 회귀 민감도 (Supp. Fig. 10)*

**내용 요약 예상:** Random seed 변경 → ARI/NMI/Jaccard=1.00(완전 일치). Cluster 수 범위 확장(12) → median ARI 0.98, NMI 0.95, Jaccard 0.99. Linkage: Ward.D → ARI 0.89, average → ARI 0.39(민감도 높음). Gene retention threshold: top 30 → ARI 0.79, top 70 → ARI 0.95. Cell cycle/hypoxia/stress response 개별 회귀 → ARI 0.44-0.57, Jaccard 0.62-0.74(대체로 유지). 동시 회귀 → ARI 0.21, NMI 0.15, Jaccard 0.57(급감).

**Reviewer 코멘트:**

**R2-4 (안정성 정량화) — 저자 대응 양호:**
- Previously "highly stable across all perturbation settings" → 구체적 수치로 대체.
- Average linkage의 민감도(ARI 0.39)가 상당히 높음 → linkage 선택이 결과에 영향. 이 정보 투명하게 제시한 점 좋음.

**R1-2 (회귀 민감도) — 남은 우려:**
- 개별 프로그램 제거 시 MPC labels 대체로 유지 → "no single canonical program drives MPC identification" 주장 지지.
- **동시 제거 시 ARI 0.21 급감 → 저자의 "overcorrection, biologically intertwined" 해석.**
- Reviewer 관점: 이 결과는 MPC가 이들 프로그램과 독립적이지 않다는 signal. 저자의 해석은 부분적 타당성 있으나, 순환성 지적을 완전히 해소하지는 않음.
- Discussion에서 이 점을 "MPC 정체성과 canonical program의 생물학적 연관성"으로 정직하게 다루는지 확인 필요.

**핵심 질문:** "동시 회귀 시 ARI 0.21"을 이 논문 맥락에서 어떻게 해석할지. 저자는 "지나친 보정"이라고 주장하나, reviewer는 "MPC 정의가 이들 프로그램과 상당히 얽혀있다"는 대안적 해석 가능.""",

    "Supplementary Figure 12: CytoTRACE2 분석": """*🔍 Reviewer 코멘트 — CytoTRACE2 (Supp. Fig. 12)*

**내용 요약 예상:** 13명 중 4명(161_3, 161_5, 180_3, 180_5)에서만 MPC가 NPC보다 유의하게 높은 CytoTRACE2. 나머지 9명에서는 유의 차이 없음.

**Reviewer 코멘트 (Minor g):**

**저자 대응 평가:**
- "일관된 plasticity 증거"라는 표현을 "patient-dependent support"로 수정 → Good.
- CytoTRACE2의 한계 인지: developmental potency 측정 → 암세포 전이 가소성과 반드시 연관되지 않음.

**Reviewer 관점:**
- 4/13만 유의한 것 놀라운 일 아님. CytoTRACE가 주로 발달 potency 포착 → 암세포에서는 다른 factor가 더 dominant할 수 있음.
- 이 heterogeneity가 "MPCs는 homogeneous high-plasticity state"라는 단순 서사 약화.
- 이 결과가 MPC 개념의 robustness에 대해 시사하는 바: 일부 환자에서 MPC가 진정한 high-plasticity state가 아닐 수 있음. Acknowledge 필요.""",

    "Supplementary Figure 13: MAGIC imputation 영향 평가": """*🔍 Reviewer 코멘트 — MAGIC imputation 영향 (Supp. Fig. 13)*

**내용 요약 예상:** Non-imputed 데이터로 scMPC 재실행. Median ARI 0.13(범위 -0.03~1.00), NMI 0.19, Jaccard 0.52. 일부 환자(167_8, 180_5)는 거의 일치, 다른 환자는 낮은 일치. 일부 환자에서 3 consensus cluster가 더 이상 명확한 metastasis signature activity 분리 안 됨 → 확신 있는 MPC cluster 할당 불가. 저자: "주요 생물학적 결론 유지" — 후보 MPC가 EMT, invasion, metastasis signature, ALCAM/VIM/SPARC 등 독립적 마커 발현 보여줌.

**Reviewer 코멘트 (R2-5):**

**Concern — 가장 중요:**
- MPC 식별 자체가 MAGIC에 크게 의존(median ARI 0.13).
- "주요 생물학적 결론 유지" 주장이 candidate MPC 수준에서는 타당하나, **세포 집단 정의의 robustness에 대한 우려는 남음**.
- 저자가 "candidate MPCs"로 표현 제한한 것은 부분적 완화.

**검토 필요:**
- Non-imputed 데이터에서 "3 consensus cluster가 더 이상 명확한 separation을 보이지 않아 confident MPC 할당 불가"라는 결과 → 이게 단순히 클러스터링 불안정성인지, 아니면 imputation 없이는 MPC/비MPC 구분 자체가 모호하다는 의미인지.
- 만약 후자라면, MPC가 real한 cell state인지에 대한 근본적 질문이 제기됨. 저자가 이 점을 어떻게 다루는지.

**핵심 질문:** "imputation이 없어도 주요 결론이 유지되는가"에 대한 저자의 기준이 무엇인지. MPC 라벨 자체의 일치(ARI 0.13)가 낮아도, "MPCs가 metastasis-associated transcriptional state를 보인다"는 결론이 유지된다는 건가? 그렇다면 그 결론의 근거는 imputed MPC 기준으로 도출된 생물학적 특성들 → circularity 가능성."""

}

for label, txt in subsections:
    comment = results_comments.get(label, "*(세부 코멘트는 원문 확인 후 추가)*")
    send(f"💬 Reviewer 코멘트 — {label}", comment)

# Discussion
print("\n[5/5] Discussion")
send("📄 Discussion (논문 원문)", discussion_text[:3000])

discussion_comment = """*🔍 Reviewer 코멘트 — Discussion*

**내용 요약 예상:** scMPC 종합 정리: 단일세포 수준에서 MPC 식별, 진화/규제/TME 통합 관점. "computationally inferred metastasis-associated transcriptional state" 프레임. Limitation: CNV inference 한계, CellChat/pseudotime/공간 co-localization의 계산적 성격, PPI 네트워크의 단백질 수준 미검증, circularity 가능성, clinical association ≠ prediction, 샘플 크기 제한. Future direction: functional validation, clinical translation.

**Reviewer 코멘트:**

**잘 된 점 (예상):**
1. "computationally inferred metastasis-associated transcriptional state" framing — R1-1, R2-7에서 반복 요청된 핵심. Discussion에서 이 톤 유지하는지.
2. Limitation 섹션에서 (1) CNV inference, (2) CellChat/pseudotime/공간, (3) PPI 네트워크, (4) circularity, (5) clinical association ≠ prediction, (6) 샘플 크기 등 주요 한계를 정직하게 다루는지.
3. "future experimental studies"로 마무리 — 가설 생성 수준임을 재확인.

**확인 필요:**
- "predicts", "validates", "drives", "remodels" 등 definitive/causal language가 Discussion에서 완전히 제거되었는지 (R1-1, R2-7).
- Limitation이 형식적으로 나열되는 데 그치지 않고, 각 한계가 결과 해석에 어떻게 영향 미치는지 구체적으로 논의하는지.
- Clinical association 주장(METABRIC HR=1.17)이 "association" 수준임을 Discussion에서 명확히 reiterate 하는지.

**종합 평가:**
- Discussion이 "our findings provide a systems-level view of transcriptomic features associated with metastatic progression" 정도 톤으로 정리된다면 acceptable.
- "our work provides comprehensive view"로 요약하면서도 "these findings should be interpreted as identifying a computationally inferred...rather than providing direct functional evidence"라는 문구가 Discussion 어딘가에 있는지 확인. 이 한 문장이 논문의 해석 프레임 전체를 규정.

**최종 Reviewer 종합:**
이 논문은 computational framework로서 상당한 thoroughness를 갖추고 있으며, reviewer 지적에 대해 대체로 성실하게 대응함. 다만 다음에 유의:
1. RGS 선택 위양성 — 미해결
2. GSE44408 dual role — "threshold calibration"으로 명시했으나 완전한 독립 검증은 아님
3. MAGIC 의존성 — median ARI 0.13 → 세포 집단 정의의 robustness 우려
4. 동시 회귀 ARI 0.21 → MPC- canonical program 관계 해석에 주의 필요

현재의 "clinical association" framing 안에서는 acceptable 수준이나, prediction/utility 주장으로 확장하려면 추가 검증 필요."""

send("💬 Reviewer 코멘트 — Discussion", discussion_comment)

print("\n" + "="*60)
print("모든 섹션 전송 완료")
print("="*60)
