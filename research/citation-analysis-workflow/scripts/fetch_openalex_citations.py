"""
OpenAlex 인용 논문 수집 스크립트 (citation-analysis-workflow 스킬 지원)

사용법:
    python fetch_openalex_citations.py <openalex_id> [per_page] [max_total]

예시:
    python fetch_openalex_citations.py W4284973934
    python fetch_openalex_citations.py W4284973934 200 300

출력:
    수집된 인용 논문 목록을 JSON으로 stdout에 출력
    (파이프라인 후속 단계에서 파싱 가능)
"""

import urllib.request
import json
import sys
import time
import random


def fetch_citations(openalex_id: str, per_page: int = 200, max_total: int = 300) -> list[dict]:
    """
    OpenAlex API로 특정 논문을 인용한 논문 목록 수집.
    
    올바른 엔드포인트: /works?filter=cites:{openalex_id}
    잘못된 엔드포인트: /works/{openalex_id}/cited_by (→ 원 논문 메타데이터만 반환)
    """
    all_results = []
    page = 1

    while len(all_results) < max_total:
        url = (
            f"https://api.openalex.org/works"
            f"?filter=cites:{openalex_id}"
            f"&per_page={per_page}"
            f"&page={page}"
            f"&sort=cited_by_count:desc"
        )

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"HTTP 오류 {e.code}: {e.reason}", file=sys.stderr)
            if e.code == 429:  # Rate limit
                wait = 5 + random.random() * 3
                print(f"Rate limit — {wait:.1f}초 대기 후 재시도", file=sys.stderr)
                time.sleep(wait)
                continue
            raise

        results = data.get("results", [])
        if not results:
            break

        all_results.extend(results)
        page += 1

        # 페이지가 덜 채워졌으면 마지막 페이지
        if len(results) < per_page:
            break

        # Rate limit 방지: 0.3~0.8초 랜덤 대기
        time.sleep(0.3 + random.random() * 0.5)

    # DOI 기준 중복 제거
    seen_dois = set()
    unique_results = []
    for r in all_results:
        doi = r.get("doi") or ""
        if doi not in seen_dois:
            seen_dois.add(doi)
            unique_results.append(r)

    return unique_results


def extract_summary(papers: list[dict], top_n: int = 20) -> dict:
    """수집 결과에서 분석용 요약 정보 추출."""
    total = len(papers)
    
    # 연도 분포
    year_dist = {}
    for p in papers:
        y = p.get("publication_year", "unknown")
        year_dist[y] = year_dist.get(y, 0) + 1
    
    # Top N (인용 수 기준)
    sorted_papers = sorted(papers, key=lambda p: p.get("cited_by_count", 0), reverse=True)
    top_n_papers = []
    for i, p in enumerate(sorted_papers[:top_n]):
        top_n_papers.append({
            "rank": i + 1,
            "title": p.get("display_name", "N/A"),
            "doi": p.get("doi", "N/A"),
            "year": p.get("publication_year", "?"),
            "cited_by_count": p.get("cited_by_count", 0),
            "authors": [
                a.get("display_name", "")
                for a in p.get("authorships", [])[:3]
                if a.get("display_name")
            ],
            "journal": (
                p.get("primary_location", {}).get("source", {}).get("display_name", "")
                if isinstance(p.get("primary_location"), dict)
                else ""
            ),
        })
    
    # 총 인용 수 (OpenAlex 기준, 원 논문의 cited_by_count와 다름에 주의)
    total_citations = sum(p.get("cited_by_count", 0) for p in papers)
    
    return {
        "total_collected": total,
        "year_distribution": dict(sorted(year_dist.items())),
        "top_n": top_n_papers,
        "total_citations_sum": total_citations,
    }


def main():
    if len(sys.argv) < 2:
        print(f"사용법: python {sys.argv[0]} <openalex_id> [per_page] [max_total]", file=sys.stderr)
        print("예시: python fetch_openalex_citations.py W4284973934", file=sys.stderr)
        sys.exit(1)

    openalex_id = sys.argv[1]
    per_page = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    max_total = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    print(f"=== OpenAlex 인용 논문 수집 ===", file=sys.stderr)
    print(f"대상: {openalex_id}", file=sys.stderr)
    print(f"per_page={per_page}, max_total={max_total}", file=sys.stderr)

    papers = fetch_citations(openalex_id, per_page, max_total)
    print(f"수집 완료: {len(papers)}건", file=sys.stderr)

    summary = extract_summary(papers)

    output = {
        "openalex_id": openalex_id,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "summary": summary,
        "papers": [
            {
                "title": p.get("display_name", ""),
                "doi": p.get("doi", ""),
                "year": p.get("publication_year", 0),
                "cited_by_count": p.get("cited_by_count", 0),
                "openalex_id": p.get("id", ""),
            }
            for p in papers
        ],
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
