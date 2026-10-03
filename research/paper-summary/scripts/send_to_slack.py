#!/usr/bin/env python3
"""
이 대화 내용을 Slack DM으로 전송.
"""
import os, re, html
from slack_sdk.web import WebClient

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

token = env.get('SLACK_BOT_TOKEN', '')
channel = "D0AMMSX1NQ2"  # DM 채널

c = WebClient(token=token)

message = """*JTRM-D-26-00308 R2 리뷰어 응답 검토 결과*

📄 *논문:* Integrative Multi-Modal Transcriptomic Identification of Metastatic Potential Cells Reveals Mechanistic Insights and Pro-Metastatic Ecosystems in Breast Cancer
📋 *식별자:* JTRM-D-26-00308R2
🔬 *프레임워크:* scMPC — 전이 관련 마커 + matched primary/metastatic bulk transcriptomes 기반 transfer-learning MPC 식별
📊 *데이터:* 림프절 전이 유방암 환자 26명 scRNA-seq

---

*✅ 잘 대응된 부분*

1. *인과관계 언어 완화 (R1-1)*
   - "drive", "remodel", "shape", "induce", "originated from" → "associated with", "predicted to engage", "consistent with" 등으로 Abstract부터 Figure 제목까지 전면 수정

2. *CellChat/공간 상호작용 주장 완화 (R1-1A)*
   - "predicted ligand-receptor interactions"로 수정, Discussion에 단백질 수준 검증 필요성 명시
   - 단일 환자 관찰(VEGFA-VEGFR1 180-3, C3-C3AR1 195-1, CXCL12 161-5)임을 인정

3. *순환성(circularity) 문제 대응 (R1-2)*
   - ALCAM, VIM, SPARC → 22개 M_signatures에 없음 → 독립 검증 마커로 사용
   - SOX9, NEAT1, CCL5 → 포함됨 → supportive로만 제시
   - Cell cycle, hypoxia, stress response 회귀 민감도 분석 수행 + 구체적 수치(ARI 0.57, Jaccard 0.74 등)

4. *임상 "predictor" 주장 철회 (R1-3)*
   - "predictor", "independent predictor", "clinically actionable" 용어 전부 삭제
   - TCGA-BRCA 분석 제거 (조정 후 유의하지 않아서)
   - METABRIC 집중: HR=1.17 (1.04–1.32, P=0.011), NPI-adjusted HR=1.16 (1.03–1.31, P=0.015)

5. *Scissor 일관성 문제 해결 (Minor 6)*
   - Scissor 3/13 vs scMPC 13/13 환자 식별, 구체적 수치로 명확히

6. *통계적 혼동 수정 (R1-5, Minor i)*
   - "95% CI" → "95% permutation-null interval"로 정정
   - Supplementary Table에 모든 edge별 통계 추가, 부트스트랩 CI 보완

---

*⚠️ 남는 우려 / Slack 논의 포인트*

1. *RGS 선택의 union-based top 10% 위양성 (R1-4, R2-1)*
   - 100만 개 RGS 중 union-based 선택 → 저자는 "potentially retain chance-associated" 인정
   - 순열 분석은 이미 선택된 RGS가 무작위보다 나은지만 평가 → 선택 과정 자체의 위양성률은 미해결

2. *GSE44408의 dual role (R2-2)*
   - Discovery gene ranking에도 기여 + threshold tuning에도 사용
   - "threshold-calibration dataset"으로 변경했으나 완전한 독립 검증은 아님
   - Discovery에 이미 사용된 데이터셋으로 threshold 튜닝 → 과적합 가능성

3. *MAGIC imputation 의존성 (R2-5)*
   - Non-imputed 데이터로 재실행: median ARI 0.13, NMI 0.19, Jaccard 0.52
   - 일부 환자(167_8, 180_5)는 거의 동일, 다른 환자는 낮은 일치
   - 13명 중 일부에서 세 consensus cluster가 더 이상 명확한 metastasis signature activity 분리 안 됨 → 확신 있는 MPC cluster 할당 불가
   - 저자는 "주요 생물학적 결론 유지" 주장하나 "candidate MPCs"로 표현 제한

4. *동시 회귀 시 ARI 0.21로 급감 (R1-2)*
   - 세 프로그램 동시 제거 시 ARI=0.21, NMI=0.15
   - 저자: "overcorrection, biologically intertwined" → 부분적 타당하나 순환성 지적 완전 해소는 아님

---

*💬 Slack에서 이어서 논의할 수 있습니다*
게이트웨이가 Socket Mode로 실행 중이므로, Slack에서 `payment` 봇에게 DM 또는 스레드에서 멘션하면 Hermes가 응답합니다."""

try:
    response = c.chat_postMessage(
        channel=channel,
        text=message,
        parse="mrkdwn",
    )
    print(f"✅ 전송 성공: ts={response['ts']}, channel={response['channel']}")
except Exception as e:
    print(f"❌ 전송 실패: {e}")
