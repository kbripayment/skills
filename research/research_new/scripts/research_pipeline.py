#!/usr/bin/env python3
"""
research_new 스킬 — 매일 뉴스레터 파이프라인 메인 오케스트레이터.

워크플로:
1. paper_search.search_all() → 오늘 업로드된 논문 수집
2. local_llm_summarize.summarize_paper() → Local LLM + Vision LLM 요약
3. slack_research_notifier.send_to_slack() → Slack 채널 알림

Cron 진입점: research_pipeline.py
"""

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

# Windows 콘솔(cp949) 이모지/한글 출력 오류 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 스킬 스크립트 디렉토리 추가 (상대 임포트용)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from paper_search import search_all, Paper
from local_llm_summarize import summarize_paper
from slack_research_notifier import (
    send_to_slack,
    send_error_to_slack,
    build_daily_message,
    PaperWithSummary,
)

from dotenv import load_dotenv

# Hermes 전역 .env 우선 로드 (라이브 시크릿)
HERMES_ENV = os.path.expanduser(r"~\AppData\Local\hermes\.env")
if os.path.exists(HERMES_ENV):
    load_dotenv(HERMES_ENV)

# 로컬 스킬 .env 로드 (토픽, 편수 설정 등)
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_ENV = os.path.join(SKILL_ROOT, ".env")
if os.path.exists(LOCAL_ENV):
    load_dotenv(LOCAL_ENV)

# ------------------------------------------------------------------
# 로깅 설정 (로테이션: 5MB × 3 백업)
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            os.path.join(SCRIPT_DIR, "research_pipeline.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("research_pipeline")

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    """환경변수를 안전하게 int로 읽음 (잘못된 값이면 기본값)."""
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        logger.warning(f"환경변수 {name}이(가) 정수가 아님 — 기본값 {default} 사용")
        return default


TOPIC = os.getenv("RESEARCH_TOPIC", "Cancer Immunotherapy")
MAX_RESULTS = _env_int("RESEARCH_MAX_RESULTS", 5)
LOOKBACK_DAYS = _env_int("RESEARCH_LOOKBACK_DAYS", 1)
# 키워드당 선발 편수: search_all이 저널 IF 우선으로 키워드별 상위 N건 선출하고,
# 검색 실패/미달 키워드의 몫은 잔여 풀에서 IF 순으로 재배분한다.
MAX_PER_KEYWORD = _env_int("RESEARCH_MAX_PAPERS_PER_KEYWORD", 5)
# 안전망 절대 상한 (선발 후에도 비정상적으로 많으면 시간예산 보호로 절단)
MAX_TOTAL_PAPERS = _env_int("RESEARCH_MAX_TOTAL_PAPERS", 30)
# 글로벌 전체 파이프라인 마감시간(초). 검색 + 요약 + 전송의 총합 상한 (기본 3600초 = 1시간)
# Hermes Cron 타임아웃(10800s = 3시간)의 1/3 지점에서 무조건 종료되도록 강제
# SKILL.md 및 하위 호환을 위해 RESEARCH_TIME_BUDGET_SECS와 RESEARCH_GLOBAL_DEADLINE_SECS 모두 지원
TIME_BUDGET_SECS = _env_int(
    "RESEARCH_TIME_BUDGET_SECS",
    _env_int("RESEARCH_GLOBAL_DEADLINE_SECS", 3600)
)
GLOBAL_DEADLINE_SECS = TIME_BUDGET_SECS
# 검색 단계에 허용할 최대 시간(초) (기본 600초 = 10분)
SEARCH_TIMEOUT_SECS = _env_int("RESEARCH_SEARCH_TIMEOUT_SECS", 600)
# Slack 메시지 빌드 및 전송에 확보할 최소 안전 버퍼 시간 (초)
SLACK_BUFFER_SECS = 180


# ------------------------------------------------------------------
# 파이프라인
# ------------------------------------------------------------------

def convert_to_slack_paper(paper: Paper) -> Tuple[PaperWithSummary, str]:
    """Paper → PaperWithSummary 변환 (요약 및 상태 반환). Vision LLM 미사용."""
    result = summarize_paper(paper)
    return (
        PaperWithSummary(
            source=paper.source,
            title=paper.title,
            paper_id=paper.paper_id,
            url=paper.url,
            summary=result.summary,
            abstract=paper.abstract,
            authors=paper.authors,
            published_date=paper.published_date,
        ),
        result.status,
    )


def _placeholder_paper(paper: Paper, reason: str) -> PaperWithSummary:
    """LLM 요약 없이 기본 정보만으로 전송용 객체 생성 (요약 실패/예산 초과/서킷 브레이커 공용)."""
    abstract_text = paper.abstract or ""
    if not abstract_text and paper.source == "elsevier":
        abstract_text = paper.raw.get("dc:description", "") or paper.raw.get("dc:abstract", "") or ""
    abstract_clean = abstract_text.strip()
    summary = f"초록 ({reason}): {abstract_clean[:600]}" if abstract_clean else reason
    return PaperWithSummary(
        source=paper.source,
        title=paper.title,
        paper_id=paper.paper_id,
        url=paper.url,
        summary=summary,
        abstract=abstract_clean[:300],
        authors=paper.authors,
        published_date=paper.published_date,
    )


def run_pipeline(topic: Optional[str] = None, lookback_days: Optional[int] = None) -> bool:
    """
    전체 파이프라인 실행.
    Args는 생략 시 모듈 레벨 설정값(.env) 사용 — import 재사용/테스트 시 안전.
    Returns: 성공 여부 (True/False)
    """
    pipeline_start = time.monotonic()
    if topic is None:
        topic = TOPIC
    if lookback_days is None:
        lookback_days = LOOKBACK_DAYS

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    date_str = now.strftime("%m/%d")
    logger.info(f"=== Research Pipeline 시작: {topic} (KST-{lookback_days}일)")

    try:
        # 1. 검색 + 키워드별 선발 (저널 IF 우선, 키워드당 MAX_PER_KEYWORD건)
        # 검색 단계에 데드라인을 전달하여 검색 지연으로 크론 예산이 잠식되는 것을 방지
        logger.info("[1/4] 논문 검색 중...")
        search_deadline = pipeline_start + SEARCH_TIMEOUT_SECS
        papers = search_all(
            topic,
            max_results=MAX_RESULTS,
            lookback_days=lookback_days,
            per_keyword=MAX_PER_KEYWORD,
            deadline=search_deadline,
        )
        logger.info(
            f"  검색 완료: {len(papers)}건 (키워드당 {MAX_PER_KEYWORD}건, 저널 IF 우선, "
            f"소요 시간: {time.monotonic() - pipeline_start:.1f}s)"
        )

        # 안전망 절대 상한 (선발 로직 이중 방어)
        if MAX_TOTAL_PAPERS and len(papers) > MAX_TOTAL_PAPERS:
            logger.warning(f"  절대 상한 {MAX_TOTAL_PAPERS}건 초과 → 절단 ({len(papers)}건 → {MAX_TOTAL_PAPERS}건)")
            papers = papers[:MAX_TOTAL_PAPERS]

        if not papers:
            msg = f"🌙 [{date_str}] {topic} — 오늘은 새 논문이 없습니다. (0건)"
            send_to_slack(msg)
            logger.info("결과 없음, Slack 알림 전송 (빈 메시지)")
            return True

        # 2. 요약 (글로벌 마감 시간 및 명시적 상태 기반 서킷 브레이커)
        logger.info("[2/4] Local LLM 요약 중...")
        slack_papers: List[PaperWithSummary] = []
        consecutive_llm_failures = 0
        total_llm_failures = 0
        CIRCUIT_BREAKER_CONSECUTIVE = 2  # 연속 2회 실제 LLM 실패 시 발동
        CIRCUIT_BREAKER_TOTAL = 4        # 교대 실패(fail-ok-fail-ok) 대비 누적 4회 실패 시 발동

        for i, paper in enumerate(papers):
            elapsed = time.monotonic() - pipeline_start
            remaining = GLOBAL_DEADLINE_SECS - elapsed

            # 1) 전체 마감 시간(Global Deadline) 방어선: Slack 발송 버퍼 미달 시 강제 탈출
            if remaining < SLACK_BUFFER_SECS:
                logger.warning(
                    f"  글로벌 데드라인 잔여 시간({remaining:.0f}s) 부족 → "
                    f"남은 {len(papers) - i}건은 요약 생략 후 즉시 Slack 전송으로 전환"
                )
                slack_papers.append(_placeholder_paper(paper, "전체 시간 예산 초과"))
                continue

            # 2) 서킷 브레이커 방어선: 연속 또는 누적 실패 임계치 도달 시 LLM 호출 중단
            if consecutive_llm_failures >= CIRCUIT_BREAKER_CONSECUTIVE or total_llm_failures >= CIRCUIT_BREAKER_TOTAL:
                logger.warning(
                    f"  서킷 브레이커 발동 (연속 {consecutive_llm_failures}회 / 누적 {total_llm_failures}회 LLM 실패) → "
                    f"남은 논문 원문 초록으로 즉시 대체"
                )
                slack_papers.append(_placeholder_paper(paper, "LLM 지연 대체"))
                continue

            logger.info(f"  [{i+1}/{len(papers)}] {paper.source}: {paper.title[:60]}...")
            try:
                sp, status = convert_to_slack_paper(paper)
                if status == "ok":
                    consecutive_llm_failures = 0  # 오직 실제 LLM 성공 시에만 카운터 리셋!
                elif status == "llm_failed":
                    consecutive_llm_failures += 1
                    total_llm_failures += 1
                # status in ("no_content", "skipped"): 초록 없음 등은 카운터를 리셋하지 않고 보존!

                slack_papers.append(sp)
            except Exception as e:
                logger.error(f"  요약 실패 ({paper.paper_id}): {e}")
                consecutive_llm_failures += 1
                total_llm_failures += 1
                slack_papers.append(_placeholder_paper(paper, f"요약 실패: {e}"))

        # 3. Slack 메시지 빌드
        logger.info("[3/4] Slack 메시지 빌드 중...")
        message = build_daily_message(topic, slack_papers, date_str)
        logger.info(f"  메시지 길이: {len(message)}자")

        # 4. Slack 전송
        logger.info("[4/4] Slack 전송 중...")
        success = send_to_slack(message)

        if success:
            logger.info(f"=== Pipeline 완료: {len(slack_papers)}건 전송 성공 ===")
        else:
            logger.error("=== Pipeline 완료: Slack 전송 실패 ===")

        return success

    except Exception as e:
        logger.error(f"Pipeline 실행 중 예상치 못한 에러: {e}", exc_info=True)
        error_msg = f"Research Pipeline 실행 실패:\nTopic: {topic}\nError: {str(e)}"
        try:
            send_error_to_slack(error_msg)
        except Exception as notify_err:
            # 에러 알림 자체의 실패가 원본 예외를 가리지 않도록 함
            logger.error(f"Slack 에러 알림 전송도 실패: {notify_err}")
        return False


# ------------------------------------------------------------------
# 진입점
# ------------------------------------------------------------------

if __name__ == "__main__":
    try:
        # 명령줄 인자: topic, days (선택) — 전역 오염 없이 파라미터로 전달
        arg_topic = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].strip() else None
        arg_days = None
        if len(sys.argv) > 2:
            try:
                arg_days = int(sys.argv[2])
            except ValueError:
                logger.warning(f"잘못된 lookback_days 인자 ({sys.argv[2]}) — 기본값({LOOKBACK_DAYS}) 사용")

        logger.info(
            f"Topic: {arg_topic or TOPIC}, Lookback: {arg_days if arg_days is not None else LOOKBACK_DAYS}일, "
            f"MaxResults: {MAX_RESULTS}, PerKeyword: {MAX_PER_KEYWORD}, TotalGuard: {MAX_TOTAL_PAPERS}, TimeBudget: {TIME_BUDGET_SECS}s"
        )

        success = run_pipeline(topic=arg_topic, lookback_days=arg_days)
        sys.exit(0 if success else 1)
    except Exception as fatal_err:
        logger.error(f"파이프라인 실행 준비/종료 중 치명적 오류: {fatal_err}", exc_info=True)
        try:
            send_error_to_slack(f"Research Pipeline 비정상 종료:\nError: {fatal_err}")
        except Exception as notify_err:
            logger.error(f"Slack 에러 알림 전송 실패: {notify_err}")
        sys.exit(1)
