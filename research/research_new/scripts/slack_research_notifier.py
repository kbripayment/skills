#!/usr/bin/env python3
"""
Slack 알림 전송 모듈.

- `.env`에서 SLACK_BOT_TOKEN, SLACK_CHANNEL 파싱
- 블로트포인트 메시지 포맷 (한국어 + Markdown)
- Rate limit 대응: 큰 메시지는 여러 청크로 분할

참고: slack-content-sharing 스킬의 .env 파싱 패턴 재사용.
     Windows 경로 문제 회피: C:/Users/... 사용.
"""

import os
import re
import time
import logging
from datetime import datetime, timezone
from typing import List, Optional
from dataclasses import dataclass

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

# Hermes 전역 .env 우선 로드 (라이브 시크릿)
HERMES_ENV = os.path.expanduser(r"~\AppData\Local\hermes\.env")
if os.path.exists(HERMES_ENV):
    load_dotenv(HERMES_ENV)

# 로컬 스킬 .env 로드 (설정값)
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_ENV = os.path.join(SKILL_ROOT, ".env")
if os.path.exists(LOCAL_ENV):
    load_dotenv(LOCAL_ENV)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------

SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#research-updates")
SLACK_BOT_NAME = os.getenv("SLACK_BOT_NAME", "Research Bot")

# Slack 메시지 한도 (텍스트 기준 약 40,000자, 안전하게 3,000자로 분할)
MAX_MESSAGE_CHARS = 3000


# ------------------------------------------------------------------
# Slack 클라이언트 초기화
# ------------------------------------------------------------------

def get_slack_client() -> Optional[WebClient]:
    """`.env`에서 토큰을 파싱해 Slack WebClient 생성 (호출 시점에 재조회)."""
    token = os.getenv("SLACK_BOT_TOKEN", "") or SLACK_TOKEN
    if not token:
        logger.error("SLACK_BOT_TOKEN이 .env에 설정되어 있지 않습니다.")
        return None
    return WebClient(token=token)


# ------------------------------------------------------------------
# 데이터 모델
# ------------------------------------------------------------------

@dataclass
class PaperWithSummary:
    """요약된 논문 정보 (Slack 전송용). Vision LLM 미사용 — 이미지 관련 필드 제외."""
    source: str
    title: str
    paper_id: str
    url: str
    summary: str
    abstract: str
    authors: List[str]
    published_date: str
    score: float = 0.0  # 관련도/영향력 점수 (선택)


# ------------------------------------------------------------------
# 메시지 빌더
# ------------------------------------------------------------------

def _truncate(text: str, limit: int = 200) -> str:
    """텍스트를 지정 길이로 자르고 '...' 추가."""
    if not text:
        return ""
    return text[:limit].strip() + "..." if len(text) > limit else text.strip()


_SUMMARY_LABEL_RE = re.compile(
    r"^\s*\*{0,2}\s*(목적|결과|목표|배경|방법|한계|의의|Purpose|Aim|Result|Results|Findings|Conclusion)\s*\*{0,2}\s*[:：]\s*\*{0,2}",
    re.IGNORECASE,
)


def _parse_summary(summary: str) -> tuple:
    """
    LLM 요약 텍스트에서 (목적, 결과) 추출.

    - '목적: ...' / '**결과:** ...' 등 라벨 행을 인식해 값만 반환
    - 방법/한계 등 다른 라벨 행은 무시
    - 파싱 실패 시 ("", "") — 호출부가 폴백 렌더링 처리
    """
    purpose, result = "", ""
    for raw in (summary or "").splitlines():
        line = raw.strip()
        if not line or not _SUMMARY_LABEL_RE.match(line):
            continue
        m = _SUMMARY_LABEL_RE.match(line)
        label = m.group(1).lower()
        value = line[m.end():].strip()
        if label in ("목적", "목표", "배경", "purpose", "aim") and not purpose:
            purpose = value
        elif label in ("결과", "result", "results", "findings", "conclusion") and not result:
            result = value
    return purpose, result


def build_daily_message(
    topic: str,
    papers: List[PaperWithSummary],
    date_str: Optional[str] = None,
) -> str:
    """
    오늘자 리서치 다이제스트 메시지 빌드.

    논문당 4항목만 출력: 제목 / 링크 / 목적 / 결과 요약.
    포맷:
    🌙 [08/19] Topic — N건 발견

    📄 PubMed (X건)

    • 제목
      • 목적: ...
      • 결과: ...

      🔗 https://...
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%m/%d")

    # 출처별 그룹화
    by_source: dict[str, List[PaperWithSummary]] = {}
    for p in papers:
        by_source.setdefault(p.source, []).append(p)

    lines: List[str] = []
    header = f"🌙 [{date_str}] {topic} — {len(papers)}건 발견\n"
    lines.append(header)

    source_labels = {
        "pubmed": "PubMed",
        "biorxiv": "bioRxiv",
        "semantic_scholar": "Semantic Scholar",
        "springer": "Springer",
        "elsevier": "Elsevier",
    }

    for source, source_papers in by_source.items():
        label = source_labels.get(source, source.title())
        lines.append(f"\n📄 {label} ({len(source_papers)}건)")
        lines.append("")  # 빈 줄

        for p in source_papers:
            # 출력 포맷: 1) 제목 2) 링크 3) 목적 4) 결과 요약 (그 외 생략)
            lines.append(f"• {p.title}")
            lines.append("")

            purpose, result = _parse_summary(p.summary)
            if purpose:
                lines.append(f"  • 목적: {_truncate(purpose, 500)}")
            if result:
                # 결과는 길이 제한 없이 상술 — Slack 청킹(3000자)이 넘침 처리
                lines.append(f"  • 결과: {_truncate(result, 4000)}")
            if not purpose and not result:
                # 다중 라인 초록의 줄바꿈을 공백으로 정규화하여 최대 500자까지 풍부하게 표시 (첫 2줄 잘림 방지)
                cleaned_text = " ".join(l.strip() for l in (p.summary or "").splitlines() if l.strip())
                if cleaned_text:
                    lines.append(f"  • {_truncate(cleaned_text, 500)}")
            lines.append("")

            lines.append(f"  🔗 {p.url}")
            lines.append("")

    # 푸터
    lines.append("")
    lines.append("---")
    lines.append(f"Sent by {SLACK_BOT_NAME} | 자동 리서치 봇")

    return "\n".join(lines)


def split_large_message(message: str, max_chars: int = MAX_MESSAGE_CHARS) -> List[str]:
    """메시지를 max_chars 이하 청크로 분할 (문단 경계 유지)."""
    if len(message) <= max_chars:
        return [message]

    chunks: List[str] = []
    current = ""

    for line in message.split("\n"):
        if len(current) + len(line) + 1 > max_chars:
            if current:
                chunks.append(current)
                current = ""
            # 개별 라인이 너무 길면 강제 분할
            if len(line) > max_chars:
                for i in range(0, len(line), max_chars):
                    chunks.append(line[i : i + max_chars])
            else:
                current = line + "\n"
        else:
            current += line + "\n"

    if current:
        chunks.append(current)

    return chunks


# ------------------------------------------------------------------
# 전송
# ------------------------------------------------------------------

def send_to_slack(
    message: str,
    channel: Optional[str] = None,
    blocks: Optional[List[dict]] = None,
    client: Optional[WebClient] = None,
) -> bool:
    """
    Slack 채널에 메시지 전송.

    - 큰 메시지는 자동으로 여러 청크로 분할
    - blocks (구조화된 레이아웃) 지원 (선택)
    - Rate limit 대응: chat_write 스코프 필요
    """
    if channel is None:
        channel = SLACK_CHANNEL
    if client is None:
        client = get_slack_client()
    if not client:
        logger.error("Slack 클라이언트를 생성할 수 없습니다.")
        return False

    chunks = split_large_message(message)
    success = True

    for i, chunk in enumerate(chunks):
        try:
            client.chat_postMessage(
                channel=channel,
                text=chunk,
                parse="mrkdwn",  # Markdown 렌더링
                # blocks=blocks,  # 선택: 구조화 레이아웃
            )
            logger.info(f"Slack 전송 완료 (청크 {i+1}/{len(chunks)})")
            if i < len(chunks) - 1:
                # 다음 청크 전 짧은 대기
                time.sleep(1)
        except SlackApiError as e:
            logger.error(f"Slack 전송 실패 (청크 {i+1}): {e.response['error']}")
            # rate_limited → retry-after 확인
            if e.response["error"] == "ratelimited":
                retry_after = e.response.headers.get("Retry-After", "30")
                logger.warning(f"Rate limited. {retry_after}s 후 재시도...")
                time.sleep(int(retry_after))
                try:
                    client.chat_postMessage(channel=channel, text=chunk, parse="mrkdwn")
                    logger.info("재전송 성공")
                except SlackApiError as e2:
                    logger.error(f"재전송 실패: {e2.response['error']}")
                    success = False
            else:
                success = False

    return success


def send_error_to_slack(error_msg: str, channel: Optional[str] = None) -> bool:
    """에러 알림을 Slack으로 전송."""
    full_msg = f"⚠️ Research Bot 에러:\n{error_msg}\n\n시간: {datetime.now().isoformat()}"
    return send_to_slack(full_msg, channel=channel)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

if __name__ == "__main__":
    test_msg = """🌙 [08/19] Cancer Immunotherapy — 3건 발견

📄 PubMed (2건)

• PMID:31234567 | Targeting PD-1 in T Cell Exhaustion
  • 핵심: T세포 고절에서 PD-1 억제 → 재활성화
  • 방법: mouse melanoma model
  • 결과: 종양 성장 75% 억제

🔗 https://pubmed.ncbi.nlm.nih.gov/31234567/

📄 bioRxiv (1건)

• bioRxiv:2408.12345 | Diffusion Models for Protein Design
  • 핵심: 단백질 fold 예측 → 생성 모델링
  • 데이터: 4,721개 단백질 구조
"""
    success = send_to_slack(test_msg)
    print(f"전송 {'성공' if success else '실패'}")
