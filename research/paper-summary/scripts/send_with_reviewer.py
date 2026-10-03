#!/usr/bin/env python3
"""PDF 본문에서 Extraced text 가져오기 (줄번호 제거 + reviewer 의견 포함)."""
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


def extract_section(text, start_kw, end_kw_or_pos=None):
    """섹션 텍스트 추출 (줄번호 제거 포함)."""
    start = text.find(start_kw)
    if start == -1:
        return ""
    # 줄번호 제거: "  123  " 패턴 → 공백 하나로 치환
    def clean(text):
        return re.sub(r'\n?\s*\d{1,4}\s*\n?', ' ', text)
    
    if end_kw_or_pos is None:
        end = len(text)
    elif isinstance(end_kw_or_pos, str):
        end = text.find(end_kw_or_pos, start)
        if end == -1:
            end = len(text)
    else:
        end = end_kw_or_pos
    
    raw = text[start:end]
    return clean(raw).strip()

def send_slack(c, channel, label, text, max_len=2400):
    """Slack DM 전송 (분할 전송 지원)."""
    msg = f"*{label}*\n\n{text}"
    if len(msg) <= max_len:
        try:
            resp = c.chat_postMessage(channel=channel, text=msg, parse="mrkdwn")
            print(f"✅ [{label}] ts={resp['ts']} ({len(msg)} chars)")
        except Exception as e:
            print(f"❌ [{label}] {e}")
        return
    
    # 긴 메시지는 문단 단위로 분할
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    cur_lbl = label
    buf = ""
    for p in paras:
        trial = f"*{cur_lbl}*\n\n" + (buf + "\n\n" + p if buf else p)
        if len(trial) > max_len and buf:
            try:
                resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
                print(f"✅ [{cur_lbl}] ts={resp['ts']} ({len(buf)} chars)")
            except Exception as e:
                print(f"❌ [{cur_lbl}] {e}")
            buf = p
            cur_lbl = f"{label} (계속)"
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
    if buf:
        try:
            resp = c.chat_postMessage(channel=channel, text=f"*{cur_lbl}*\n\n{buf}", parse="mrkdwn")
            print(f"✅ [{cur_lbl}] ts={resp['ts']} ({len(buf)} chars)")
        except Exception as e:
            print(f"❌ [{cur_lbl}] {e}")

# ── 전송할 섹션 정의 ──
# 각 섹션: (라벨, 원문라벨, 추출키워드, 종료키워드, reviewer의견)
sections = [
    {
        "slack_label": "📄 Introduction (논문 원문)",
        "clean_label": "Introduction",
        "start_kw": "Background:",
        "end_kw": "Methods",
        "reviewer_comment": """*🔍 Reviewer 관점 코멘트*

이 Introduction은 논문의 전체 그림을 잘 그려주고 있습니다. 특히:

1. EMT/pEMT만을 통한 전이 설명을 넘어 "spectrum of highly plastic cell states"로 접근한 점 — 최신 문헌(9, 10, 11)을 적절히 인용하며 배경을 설정함.

2. bulk transcriptomics의 한계를 scRNA-seq + bulk 통합(framework scMPC)으로 극복하겠다는 논리가 명확함.

3. 26명 paired primary-LN metastasis 코호트라는 데이터의 강점을 초반부터 강조.

*Reviewer로서 확인할 점:*
- "metastasis-initiating cells (MICs)" 용어와 본 연구의 "MPC" 간 관계 정립 필요 — 두 개념이 같은지, 다른지, 포함 관계인지 Introduction에서 더 명확히 하면 좋을 것.
- "actively remodel the TME" 같은 표현은 이미 R1-1에서 지적된 과잉 서술인데, Introduction에서도 등장함 (73-75라인). Discussion뿐 아니라 Introduction에서도causal language를 조금 더 조심할 여지가 있음.""",
    },
]

c = WebClient(token=env['SLACK_BOT_TOKEN'])
channel = "D0AMMSX1NQ2"

for sec in sections:
    raw = extract_section(full, sec["start_kw"], sec["end_kw"])
    print(f"\n{sec['slack_label']}: {len(raw)} chars (줄번호 제거됨)")
    
    # 원문 먼저 전송
    send_slack(c, channel, sec['slack_label'], raw[:3000])
    
    # reviewer 의견 전송
    send_slack(c, channel, f"💬 Reviewer 코멘트 ({sec['clean_label']})", sec['reviewer_comment'])

print("\n=== 전송 완료 ===")
