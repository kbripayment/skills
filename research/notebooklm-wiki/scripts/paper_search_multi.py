#!/usr/bin/env python3
"""
Multi-Repository Literature Search — thin CLI wrapper
=====================================================

검색 엔진은 `paper_search.py` 단일 모듈로 통합되었다(드리프트 방지).
이 모듈은 이전 퍼블릭 인터페이스(Paper, search_* , search_all_repos,
paper_to_dict, papers_to_display)와 CLI를 그대로 유지하는 래퍼다.

저장소: PubMed / bioRxiv / Semantic Scholar / Springer Nature OA / Elsevier
ScienceDirect — 전부 paper_search 쪽에서 구현된다.
"""

import os
import sys

# Windows 콘솔(cp949) 이모지/한글 출력 오류 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from paper_search import (  # noqa: F401  (재노출용)
    Paper,
    search_pubmed,
    search_biorxiv,
    search_semantic_scholar,
    search_springer,
    search_elsevier,
    search_all,
)

__all__ = [
    "Paper",
    "search_pubmed", "search_biorxiv", "search_semantic_scholar",
    "search_springer", "search_elsevier",
    "search_all", "search_all_repos",
    "paper_to_dict", "papers_to_display",
]


def search_all_repos(
    query: str,
    max_results: int = 5,
    lookback_days: int = 1,
    springer_api_key=None,
    elsevier_api_key=None,
):
    """구 search_all_repos 시그니처 호환. 명시적 키는 env에 반영 후 통합 검색."""
    if springer_api_key:
        os.environ["SPRINGER_API_KEY"] = springer_api_key
    if elsevier_api_key:
        os.environ["ELSEVIER_API_KEY"] = elsevier_api_key
    return search_all(query, max_results=max_results, lookback_days=lookback_days)


def paper_to_dict(p: Paper) -> dict:
    """Paper 객체를 Slack/NotebookLM/wiki 용 dict로 변환."""
    return {
        "source": p.source,
        "paper_id": p.paper_id,
        "title": p.title,
        "url": p.url,
        "abstract": p.abstract,
        "authors": p.authors,
        "published_date": p.published_date,
    }


def papers_to_display(papers) -> list:
    """Slack/CLI 표시용 (인덱스 포함, 초록 200자 절단)."""
    return [
        {
            "index": i + 1,
            "source": p.source,
            "paper_id": p.paper_id,
            "title": p.title,
            "url": p.url,
            "abstract": p.abstract[:200],
            "authors": p.authors,
            "published_date": p.published_date,
        }
        for i, p in enumerate(papers)
    ]


if __name__ == "__main__":
    import argparse
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv 없으면 순수 환경변수만 사용

    parser = argparse.ArgumentParser(
        description="통합 논문 검색 CLI — PubMed/bioRxiv/Semantic Scholar/Springer/Elsevier "
                    "(엔진: paper_search.py 단일 모듈)")
    parser.add_argument("query", nargs="?", help="검색 키워드 (예: 'amyloid plaque')")
    parser.add_argument("--max-results", "-m", type=int, default=5, help="소스별 최대 결과 수 (기본 5)")
    parser.add_argument("--lookback-days", "-d", type=int, default=1, help="PubMed/bioRxiv 날짜 필터 일수 (기본 1)")

    args = parser.parse_args()
    if not args.query:
        parser.print_help()
        sys.exit(1)

    papers = search_all_repos(args.query, max_results=args.max_results,
                              lookback_days=args.lookback_days)

    print(f"\n📚 키워드 '{args.query}' 검색 결과 ({len(papers)}건)")
    print("=" * 80)
    for i, p in enumerate(papers, 1):
        print(f"\n[{i}] [{p.source.upper()}] {p.title}")
        print(f"    ID: {p.paper_id}")
        print(f"    URL: {p.url}")
        print(f"    저자: {', '.join(p.authors[:3])}" + ("..." if len(p.authors) > 3 else ""))
        print(f"    발행일: {p.published_date}")
        print(f"    초록: {(p.abstract or '(없음)')[:300]}...")
    print("\n" + "=" * 80)
    print("✅ 검색 완료.")
