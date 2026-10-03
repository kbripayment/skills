#!/usr/bin/env python3
"""
논문 수집 → scite 검증 → Obsidian 정준 저장 — plans_citation.md v1.3.0

파이프라인 조립:
  ① 입력 정규화 (DOI → OpenAlex)  →  ② Scholar Cited-by 수집
  →  ③ OpenAlex 메타 보강         →  ④ 3-tier 본문 확보
  →  ⑤ 텍스트 추출 + LLM 필터     →  ⑥ scite 검증 + Obsidian 저장

사용법:
    python citation_pipeline.py --doi "10.18653/v1/N19-1423" \
        --rq "How does self-attention compare to LSTM in NLP tasks?" \
        --vault "D:/Obsidian Vault"
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# ── 경로 ──────────────────────────────────────────────────────────────

SKILL_ROOT = Path(__file__).parent.parent.resolve()
SRC_DIR = SKILL_ROOT / "src"
VENV_PYTHON = Path.home() / "AppData" / "Local" / "Temp" / "academic-mcp-venv" / "Scripts" / "python.exe"
DOWNLOAD_DIR = Path.home() / "AppData" / "Local" / "Temp" / "academic-mcp-downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ── 토큰 / 환경 로딩 ────────────────────────────────────────────────

def load_env_key(key: str) -> Optional[str]:
    """~/.hermes/.env에서 키 조회 (UTF-16 LE BOM 폴백)."""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return None
    for enc in ("utf-8-sig", "utf-8", "utf-16-le", "cp949"):
        try:
            text = env_path.read_text(encoding=enc)
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        return v.strip().strip("\"'")
        except (UnicodeDecodeError, OSError):
            continue
    return None


# ── 데이터 클래스 ─────────────────────────────────────────────────────

@dataclass
class CanonicalPaper:
    """정준화된 논문 메타데이터."""
    doi: Optional[str] = None
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    openalex_id: Optional[str] = None
    abstract: str = ""
    open_access_url: Optional[str] = None
    arxiv_id: Optional[str] = None
    referenced_works: list[str] = field(default_factory=list)
    source: str = "unknown"         # openalex | scholar | crossref
    version: str = "published"      # published | accepted | preprint
    sha256: Optional[str] = None    # PDF 해시 (attachments/ 연동)
    pdf_path: Optional[str] = None  # 임시 다운로드 경로 (raw 복사용)
    raw_path: Optional[str] = None  # Obsidian attachments/ 상대경로
    acquisition_method: str = ""    # oa_direct | web_fetch | academic_mcp | abstract_only
    acquisition_tier: int = 0


@dataclass
class SciteVerification:
    """scite Smart Citation 검증 결과."""
    doi: str = ""
    title: str = ""
    total_citations: int = 0
    supporting: int = 0
    mentioning: int = 0
    contrasting: int = 0
    unassigned: int = 0
    label: str = "unverified"      # tally 상세: supporting | mixed | contrasting | unverified
    verification_status: str = "unverified"  # plans 어휘: verified | partially_verified | unverified | unverifiable_no_doi | retracted | scite_unreachable
    unconfirmed_by_scite: list[str] = field(default_factory=list)
    evidence_snippets: list[dict] = field(default_factory=list)
    evidence_excerpt: str = ""
    source_version: str = ""
    retrieved_at: str = ""
    retraction_status: Optional[str] = None
    editorial_notice: Optional[str] = None
    error: Optional[str] = None


@dataclass
class FilteredPassage:
    """LLM 필터링 통과 passage (스펙 Step ⑤ 판정 필드 포함)."""
    section: str = ""
    text: str = ""
    score: float = 0.0
    sha256: str = ""
    rq_class: str = ""
    method_similarity: str = ""
    tfidf_score: Optional[float] = None
    confidence: str = ""
    filter_reason: str = ""
    filter_verdict: str = "kept"


# ── ① 입력 정규화 + 정준화 ──────────────────────────────────────────

def canonicalize_paper(paper: CanonicalPaper) -> CanonicalPaper:
    """Step ①: DOI 정규화 (소문자·trim·https://doi.org/ 제거)."""
    if paper.doi:
        paper.doi = paper.doi.lower().strip().replace("https://doi.org/", "")
    if paper.title:
        paper.title = paper.title.strip()
    return paper


def _normalize_text_key(s: str) -> str:
    """제목/저자 정규화 키 (소문자·영숫자/한글 외 제거·공백 단일화)."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _title_similarity(a: str, b: str) -> float:
    """정규화 제목 간 유사도 0.0~1.0 (difflib, 스펙 ≥0.85)."""
    import difflib
    return difflib.SequenceMatcher(None, _normalize_text_key(a), _normalize_text_key(b)).ratio()


def dedupe_papers(papers: list[dict]) -> list[dict]:
    """
    인용 목록 중복 제거. 키 우선순위: DOI > OpenAlex ID > 정규화(title+첫저자+year).
    version-of-record 선별은 enrich 단계의 version 필드로 판단한다.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for p in papers:
        doi = (p.get("doi") or "").lower().strip()
        if doi:
            key = f"doi:{doi}"
        elif p.get("openalex_id"):
            key = f"oa:{p['openalex_id']}"
        else:
            authors = p.get("authors") or []
            first = authors[0] if authors else ""
            key = (f"t:{_normalize_text_key(p.get('title', ''))}"
                   f"|{_normalize_text_key(first)}|{p.get('year')}")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ── OpenAlex 메타데이터 조회 ────────────────────────────────────────

async def _get_with_backoff(
    client: Any, url: str, attempts: int = 3, base_delay: float = 2.0,
) -> Any:
    """지수 백오프(2s→4s→8s) 재시도 GET. 스펙 오류 처리 표."""
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            if attempt < attempts - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
    raise last_err  # type: ignore[misc]


async def fetch_openalex_by_doi(doi: str, mailto: str = "") -> Optional[dict]:
    """DOI로 OpenAlex 메타데이터 조회 (백오프 3회)."""
    import urllib.parse
    doi_enc = urllib.parse.quote(doi, safe="")
    mailto_q = f"&mailto={urllib.parse.quote(mailto)}" if mailto else ""
    url = f"https://api.openalex.org/works/https://doi.org/{doi_enc}{mailto_q}"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await _get_with_backoff(client, url)
    except Exception as e:
        print(f"[OpenAlex] DOI 조회 실패 {doi}: {e}", file=sys.stderr)
        return None


async def fetch_openalex_by_title(
    title: str, mailto: str = "", year: Optional[int] = None,
) -> Optional[dict]:
    """
    제목으로 OpenAlex 검색 후 최적 1건 선택.
    선택 기준: 정규화 제목 유사도 + publication_year 일치 가산 (+0.2).
    """
    import urllib.parse

    mailto_q = f"&mailto={mailto}" if mailto else ""
    encoded = urllib.parse.quote(title)
    url = f"https://api.openalex.org/works?filter=title.search:{encoded}{mailto_q}&per-page=5"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            data = await _get_with_backoff(client, url)
            results = data.get("results", [])
            if not results:
                return None
            if len(results) == 1:
                return results[0]

            def _score(r: dict) -> float:
                s = _title_similarity(r.get("display_name", ""), title)
                if year and r.get("publication_year") == year:
                    s += 0.2
                return s

            best = max(results, key=_score)
            print(f"[OpenAlex] 제목 검색 {len(results)}건 중 최적 선택: "
                  f"{(best.get('display_name') or '')[:60]} "
                  f"(score={_score(best):.2f})")
            return best
    except Exception as e:
        print(f"[OpenAlex] 제목 검색 실패: {e}", file=sys.stderr)
        return None


# ── ② Scholar Cited-by 수집 ────────────────────────────────────────

def _serpapi_year(summary: str) -> Optional[int]:
    """SerpApi publication_info.summary에서 연도 추출."""
    m = re.search(r"(19|20)\d{2}", summary or "")
    return int(m.group(0)) if m else None


async def _fetch_serpapi_cited_by(
    title: str, api_key: str, max_results: int = 50,
) -> list[dict]:
    """
    SerpApi google_scholar 폴백: 제목 검색 → organic[0].inline_links.cited_by.cites_id → 인용 목록.
    Scholar 차단 시 대체 수집 경로 (scite 교차검증은 별도 단계).
    """
    import httpx
    import urllib.parse

    # SerpApi는 api_key를 query 파라미터로 요구 (공식 문서)
    async with httpx.AsyncClient(timeout=30.0) as client:
        search_url = (
            "https://serpapi.com/search.json?engine=google_scholar"
            f"&q={urllib.parse.quote(title)}"
            f"&api_key={api_key}"
        )
        search_data = await _get_with_backoff(client, search_url)
        organic = search_data.get("organic_results", [])
        if not organic:
            return []
        inline = organic[0].get("inline_links", {}) or {}
        cited_by = inline.get("cited_by", {}) or {}
        cites_id = cited_by.get("cites_id")
        if not cites_id:
            return []
        papers = []
        start = 0
        page_size = 20
        while len(papers) < max_results:
            cites_url = (
                "https://serpapi.com/search.json?engine=google_scholar"
                f"&cites={cites_id}"
                f"&num={page_size}&start={start}"
                f"&api_key={api_key}"
            )
            cites_data = await _get_with_backoff(client, cites_url)
            batch = cites_data.get("organic_results", []) or []
            if not batch:
                break
            for r in batch:
                if len(papers) >= max_results:
                    break
                pub = r.get("publication_info", {}) or {}
                authors_raw = pub.get("authors", []) or []
                if isinstance(authors_raw, str):
                    author_list = [authors_raw]
                else:
                    author_list = [a.get("name", "") for a in authors_raw if a.get("name")]
                inline = r.get("inline_links", {}) or {}
                cited = inline.get("cited_by", {}) or {}
                papers.append({
                    "title": r.get("title", ""),
                    "authors": author_list,
                    "year": _serpapi_year(pub.get("summary", "")),
                    "doi": None,  # SerpApi는 DOI 미제공 → OpenAlex 보강 단계에서 추정
                    "openalex_id": None,
                    "citation_count": cited.get("total", 0),
                    "open_access_url": (r.get("resources", [{}])[0].get("link")
                                          if r.get("resources") else None),
                    "url_scholar": r.get("link"),
                    "snippet": r.get("snippet"),
                })
            if len(batch) < page_size:
                break
            start += len(batch)
        return papers


async def collect_scholar_cited_by(
    title: str,
    max_results: int = 50,
    mailto: str = "",
) -> list[dict]:
    """
    Google Scholar Cited-by 수집.
    우선순위: SERPAPI_KEY 있으면 SerpApi cites → 실패 시 OpenAlex filter=cites:W...
    (browser_exec 실크롤링은 하네스 도구 필요 — TODO 유지, 차단 시 본 폴백 사용.)
    """
    serp_key = load_env_key("SERPAPI_KEY")
    if serp_key:
        try:
            papers = await _fetch_serpapi_cited_by(title, serp_key, max_results)
            if papers:
                print(f"[Scholar/SerpApi] 인용 논문 수집: {len(papers)}건")
                return papers
            print("[Scholar/SerpApi] 결과 없음 → OpenAlex 폴백")
        except Exception as e:
            print(f"[Scholar/SerpApi] 실패 → OpenAlex 폴백: {e}", file=sys.stderr)

    # OpenAlex filter=cites:W...로 대체 (cited_by_api_url은 최신 응답에 없음)
    openalex_result = await fetch_openalex_by_title(title)
    if not openalex_result:
        return []

    openalex_id = openalex_result.get("id", "").replace("https://openalex.org/", "")
    if not openalex_id:
        return []

    try:
        import httpx
        papers = []
        page = 1
        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(papers) < max_results:
                url = f"https://api.openalex.org/works?filter=cites:{openalex_id}&per-page=200&page={page}"
                if mailto:
                    url += f"&mailto={mailto}"
                data = await _get_with_backoff(client, url)
                results = data.get("results", [])
                if not results:
                    break
                for r in results:
                    if len(papers) >= max_results:
                        break
                    author_list = []
                    for a in r.get("authorships", []):
                        an = a.get("author", {}).get("display_name", "")
                        if an:
                            author_list.append(an)
                    papers.append({
                        "title": r.get("display_name", ""),
                        "authors": author_list,
                        "year": r.get("publication_year"),
                        "doi": (r.get("doi") or "").lower().replace("https://doi.org/", "") or None,
                        "openalex_id": r.get("id", "").replace("https://openalex.org/", ""),
                        "citation_count": r.get("cited_by_count", 0),
                        "open_access_url": r.get("open_access", {}).get("oa_url"),
                        "url_scholar": None,
                        "snippet": None,
                    })
                if len(results) < 200:
                    break
                page += 1
            return papers
    except Exception as e:
        print(f"[Scholar Fallback] 인용 논문 수집 실패: {e}", file=sys.stderr)
        return []


# ── ③ 메타데이터 보강 ───────────────────────────────────────────────

async def enrich_paper(paper: CanonicalPaper) -> CanonicalPaper:
    """OpenAlex로 논문 메타 보강."""
    if paper.doi:
        data = await fetch_openalex_by_doi(paper.doi)
    else:
        data = await fetch_openalex_by_title(paper.title, year=paper.year)

    if not data:
        return paper

    if not paper.doi and data.get("doi"):
        paper.doi = data["doi"].lower().replace("https://doi.org/", "")

    if not paper.title and data.get("display_name"):
        paper.title = data["display_name"]

    if not paper.authors and data.get("authorships"):
        paper.authors = [
            a.get("author", {}).get("display_name", "")
            for a in data["authorships"]
            if a.get("author", {}).get("display_name")
        ]

    if not paper.year and data.get("publication_year"):
        paper.year = data["publication_year"]

    if not paper.openalex_id and data.get("id"):
        paper.openalex_id = data["id"].replace("https://openalex.org/", "")

    if not paper.abstract:
        inv_ab = data.get("abstract_inverted_index")
        if inv_ab and isinstance(inv_ab, dict):
            try:
                words: dict[str, list[int]] = inv_ab
                pos_word: dict[int, str] = {}
                for w, positions in words.items():
                    for pos in positions:
                        pos_word[int(pos)] = w
                paper.abstract = " ".join(pos_word[i] for i in sorted(pos_word))
            except (ValueError, TypeError, AttributeError):
                pass

    if not paper.open_access_url:
        oa = data.get("open_access", {})
        paper.open_access_url = oa.get("oa_url")

    if not paper.referenced_works and data.get("referenced_works"):
        paper.referenced_works = [
            w.replace("https://openalex.org/", "")
            for w in data["referenced_works"]
        ]

    # arXiv ID 추출
    locations = data.get("locations", []) or []
    for loc in locations:
        src = loc.get("source", {}) or {}
        if src.get("display_name") == "arXiv":
            pdf = loc.get("pdf_url") or ""
            m = re.search(r"(\d{4}\.\d{4,5})", pdf)
            if m:
                paper.arxiv_id = m.group(1)
                break

    # Version-of-record 판별 (locations[].version)
    ver_rank = {"submittedversion": 0, "acceptedversion": 1, "publishedversion": 2}
    best_rank = -1
    for loc in locations:
        r = ver_rank.get(str(loc.get("version") or "").lower().replace(" ", ""), -1)
        if r > best_rank:
            best_rank = r
    if best_rank == 2:
        paper.version = "published"
    elif best_rank == 1:
        paper.version = "accepted"
    elif best_rank == 0:
        paper.version = "preprint"

    return paper


# ── ④ 3-tier 본문 확보 ──────────────────────────────────────────────

async def acquire_body(paper: CanonicalPaper) -> CanonicalPaper:
    """paper_acquisition.py 3-tier 실행."""
    sys.path.insert(0, str(SRC_DIR))
    from paper_acquisition import acquire_paper_body

    kwargs: dict[str, Any] = {
        "save_dir": DOWNLOAD_DIR,
        "open_access_url": paper.open_access_url,
    }
    if paper.arxiv_id:
        kwargs["paper_id"] = paper.arxiv_id
        kwargs["source"] = "arxiv"
    if paper.doi:
        kwargs["landing_url"] = f"https://doi.org/{paper.doi}"

    result = await acquire_paper_body(
        paper={"title": paper.title, "doi": paper.doi},
        **kwargs,
    )

    paper.acquisition_method = result.get("acquisition_method", "abstract_only")
    paper.acquisition_tier = result.get("tier_attempted", 0)

    pdf_path_str = result.get("pdf_path")
    if pdf_path_str and Path(pdf_path_str).exists():
        paper.pdf_path = str(pdf_path_str)
        paper.sha256 = hashlib.sha256(Path(pdf_path_str).read_bytes()).hexdigest()

    return paper


# ── ⑤ 텍스트 추출 + LLM 필터 ───────────────────────────────────────

async def extract_and_filter(
    paper: CanonicalPaper,
    research_question: str,
    threshold: float = 0.40,
    max_passages: int = 10,
    include_review: bool = False,
) -> list[FilteredPassage]:
    """text_extraction.py 필터링 실행 (include_review=True면 needs_human_review 포함)."""
    sys.path.insert(0, str(SRC_DIR))
    from text_extraction import filter_by_rq

    pdf_path = None
    if paper.pdf_path and Path(paper.pdf_path).exists():
        pdf_path = paper.pdf_path
    elif paper.sha256:
        candidates = list(DOWNLOAD_DIR.glob("*.pdf"))
        for c in candidates:
            if hashlib.sha256(c.read_bytes()).hexdigest() == paper.sha256:
                pdf_path = str(c)
                break

    if not pdf_path:
        return []

    passages_raw = filter_by_rq(
        pdf_path,
        research_question,
        threshold=threshold,
        max_passages=max_passages,
        include_review=include_review,
    )

    return [
        FilteredPassage(
            section=p["section"],
            text=p["text"],
            score=p["score"],
            sha256=p["sha256"],
            rq_class=p.get("rq_class", ""),
            method_similarity=p.get("method_similarity", ""),
            tfidf_score=p.get("tfidf_score"),
            confidence=p.get("confidence", ""),
            filter_reason=p.get("filter_reason", ""),
            filter_verdict=p.get("verdict", "kept"),
        )
        for p in passages_raw
    ]


# ── ⑥ scite 검증 ────────────────────────────────────────────────────

async def _verify_scite_async(
    doi: str, title: str, token: str,
    citing_dois: Optional[list[str]] = None,
) -> SciteVerification:
    """scite Smart Citations 조회 (async 내부) + citation_graph 교차검증."""
    from scite_client import SciteClient

    result = SciteVerification(doi=doi, title=title or "")
    try:
        async with SciteClient(token=token) as scite:
            paper_data = await scite.paper_by_doi(doi)
            if not paper_data:
                result.error = "scite에서 논문을 찾을 수 없음"
                return result

            tally = paper_data.get("tally", {})
            result.total_citations = tally.get("total", 0)
            result.supporting = tally.get("supporting", 0)
            result.mentioning = tally.get("mentioning", 0)
            result.contrasting = tally.get("contrasting", 0)
            result.unassigned = tally.get("unassigned", 0)

            notices = paper_data.get("editorialNotices") or paper_data.get("editorial_notices") or []
            if notices:
                first = notices[0] if isinstance(notices, list) else notices
                notice_type = first.get("type") if isinstance(first, dict) else str(first)
                result.retraction_status = notice_type or True
                result.editorial_notice = str(first)
            else:
                result.retraction_status = paper_data.get("retracted", False) or None
                result.editorial_notice = paper_data.get("editorial_notice")

            # 라벨(tally 상세) + 검증 상태(plans 어휘) 결정
            total = result.total_citations
            if total == 0:
                result.label = "unverified"
            elif result.contrasting > total * 0.3:
                result.label = "contrasting"
            elif result.supporting > total * 0.3:
                result.label = "supporting"
            else:
                result.label = "mixed"
            
            # verification_status 결정: retraction type에 따라 세분화
            rs = result.retraction_status
            if rs and isinstance(rs, str):
                rs_lower = rs.lower()
                if "retract" in rs_lower:
                    result.verification_status = "retracted"
                elif "correct" in rs_lower:
                    result.verification_status = "corrected"
                elif "concern" in rs_lower or "expression" in rs_lower:
                    result.verification_status = "concern_raised"
                else:
                    result.verification_status = "concern_raised"
            elif total == 0:
                result.verification_status = "unverified"
            elif result.supporting > total * 0.3:
                result.verification_status = "verified"
            else:
                result.verification_status = "partially_verified"

            # citation_graph 교차검증: 수집 목록 중 graph에 없는 DOI
            if citing_dois:
                try:
                    graph = await scite.citation_graph(doi, limit=100, direction="in")
                    gkeys: set[str] = set()
                    for k in ((graph or {}).get("papers", {}) or {}):
                        gkeys.add(str(k).lower())
                    for e in ((graph or {}).get("edges", []) or []):
                        for v in (e.get("s"), e.get("t")):
                            if v:
                                gkeys.add(str(v).lower())
                    result.unconfirmed_by_scite = [
                        d for d in citing_dois
                        if d and d.lower() not in gkeys and d.lower() != doi.lower()
                    ]
                except Exception as e:
                    print(f"[scite] citation_graph 교차검증 스킵: {e}", file=sys.stderr)

            # evidence snippet 수집 (상위 3개)
            scites = paper_data.get("citations", []) or paper_data.get("scites", [])
            scites = scites[:3]
            result.evidence_snippets = [
                {
                    "context": s.get("context", "") or s.get("snippet", ""),
                    "type": s.get("type", ""),
                    "section": s.get("section", ""),
                    "source_doi": s.get("sourceDoi", "") or s.get("source_doi", ""),
                }
                for s in scites
                if s.get("context") or s.get("snippet")
            ]
            if result.evidence_snippets:
                result.evidence_excerpt = result.evidence_snippets[0].get("context", "")
            result.source_version = str(paper_data.get("version", "v1"))
            result.retrieved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return result

    except Exception as e:
        result.error = str(e)
        result.verification_status = "scite_unreachable"
        return result


def verify_with_scite(
    doi: str, title: str = "", citing_dois: Optional[list[str]] = None,
) -> SciteVerification:
    """
    scite Smart Citations 조회 (동기 래퍼 — batch_pipeline 호환).
    asyncio.run() 중첩 문제를 피하기 위해 별도 event loop에서 실행.
    """
    result = SciteVerification(doi=doi, title=title or "")
    token = load_env_key("SCITE_ACCESS_TOKEN")
    if not token:
        result.error = "SCITE_ACCESS_TOKEN 없음"
        result.verification_status = "scite_unreachable"
        return result

    try:
        try:
            _ = asyncio.get_running_loop()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.get_event_loop()

        result = loop.run_until_complete(
            _verify_scite_async(doi, title or "", token, citing_dois=citing_dois)
        )
        # loop.close() 금지: mcp 백그라운드 태스크가 cancel scope 진입 task 불일치로
        # RuntimeError/"never awaited" 발생. gc가 자동으로 정리하므로 close 불필요.
    except Exception as e:
        result.error = str(e)
        result.verification_status = "scite_unreachable"
    return result


# ── Obsidian 저장 ────────────────────────────────────────────────────

def normalize_filename(title: str) -> str:
    """파일명으로 사용 가능한 문자열 변환."""
    s = re.sub(r'[\\\/:*?"<>|]', "_", title or "Untitled")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 120:
        s = s[:120]
    return s or "Untitled"


def _esc(s: str) -> str:
    """YAML 문자열 이스케이프 (double-quoted scalar용)."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _yaml_quote(s: str) -> str:
    """YAML double-quoted scalar로 안전하게 변환."""
    return '"' + _esc(s) + '"'


def build_obsidian_frontmatter(
    paper: CanonicalPaper,
    verification: SciteVerification,
    passages: list[FilteredPassage],
    source_doi: Optional[str] = None,
    source_title: Optional[str] = None,
) -> str:
    """
    Obsidian Markdown 프론트매터 생성 (v1.3.0).
    - source_doi/source_title: citing 논문인 경우 원논문 백링크
    - Obsidian Properties v2 호환: authors=[...] 배열 (각 요소를 따옴표로 감쌈)
    """
    lines = ["---"]
    lines.append(f"title: {_yaml_quote(paper.title)}")
    if paper.doi:
        lines.append(f"doi: {_yaml_quote(paper.doi)}")
    if paper.year:
        lines.append(f"year: {paper.year}")
    if paper.authors:
        safe = [_yaml_quote(a) for a in paper.authors[:5]]
        lines.append(f"authors: [{', '.join(safe)}]")
    if paper.openalex_id:
        lines.append(f"openalex_id: {_yaml_quote(paper.openalex_id)}")
    lines.append(f"source: {_yaml_quote(paper.source)}")
    lines.append(f"version: {_yaml_quote(paper.version)}")
    lines.append(f"sha256: {_yaml_quote(paper.sha256 or '')}")
    if paper.raw_path:
        lines.append(f"raw_pdf: {_yaml_quote(paper.raw_path)}")
    lines.append(f"acquisition_method: {_yaml_quote(paper.acquisition_method)}")
    lines.append(f"acquisition_tier: {paper.acquisition_tier}")
    lines.append(f"scite_label: {_yaml_quote(verification.label)}")
    lines.append(f"scite_verification_status: {_yaml_quote(verification.verification_status)}")
    lines.append(f"total_citations: {verification.total_citations}")
    lines.append(f"supporting: {verification.supporting}")
    lines.append(f"mentioning: {verification.mentioning}")
    lines.append(f"contrasting: {verification.contrasting}")
    if verification.evidence_excerpt:
        lines.append(f'evidence_excerpt: "{_esc(verification.evidence_excerpt[:500])}"')
    if verification.retrieved_at:
        lines.append(f'retrieved_at: "{verification.retrieved_at}"')
    if verification.retraction_status is not None:
        lines.append(f"retracted: {str(verification.retraction_status).lower()}")
    lines.append(f"passages_count: {len(passages)}")
    if source_doi:
        lines.append(f'source_doi: "{source_doi}"')
    if source_title:
        lines.append(f"cites: [[{_esc(source_title)}]]")
    lines.append("tags: [citation-paper, scite-verified]")
    lines.append(f"created: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    lines.append("---")
    return "\n".join(lines)


def get_unique_filepath(base_path: Path, sha256: Optional[str]) -> Path:
    """
    SHA256 collision 방지를 위한 고유 파일 경로 반환 (Gap d).
    - sha256 미존재 또는 base 미존재: base_path 반환
    - base 존재 + sha256 존재: {stem}_{sha256[:8]}.md suffix 추가
    """
    if not sha256 or not base_path.exists():
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix
    return base_path.parent / f"{stem}_{sha256[:8]}{suffix}"


def _find_existing_note_with_doi(vault: Path, year: str, safe_title: str, doi: Optional[str]) -> Optional[Path]:
    """같은 제목의 기존 노트 중 DOI가 일치하는 것을 찾음"""
    if not doi:
        return None
    inbox_dir = vault / "Inbox" / str(year)
    if not inbox_dir.exists():
        return None
    # 같은 제목의 노트들 검색
    for note_path in inbox_dir.glob(f"{safe_title}*.md"):
        try:
            text = note_path.read_text(encoding="utf-8", errors="ignore")
            if f'doi: "{doi}"' in text:
                return note_path
        except Exception:
            continue
    return None


def save_to_obsidian(
    paper: CanonicalPaper,
    verification: SciteVerification,
    passages: list[FilteredPassage],
    vault_path: str | Path,
    source_doi: Optional[str] = None,
    source_title: Optional[str] = None,
) -> Optional[Path]:
    """
    Obsidian vault에 논문 Markdown 저장 (v1.3.0).

    Raw PDF: {vault}/attachments/{year}/{sha256[:8]}_{safe_title}.pdf
    노트:      {vault}/Inbox/{year}/{normalized_title}[_{sha8}].md
    백링크:    source_doi / cites: [[...]] (citing 논문인 경우)

    Returns: 저장된 Path 또는 None(중복 스킵)
    """
    vault = Path(vault_path)
    if not vault.exists():
        raise FileNotFoundError(f"Obsidian vault 없음: {vault}")
    if not os.access(vault, os.W_OK):
        raise PermissionError(f"Vault 쓰기 권한 없음: {vault}")

    year = paper.year or "unknown"
    safe_title = normalize_filename(paper.title)

    # ── Raw PDF 분리 → attachments/ ─────────────────────────────
    raw_rel_path: Optional[str] = None
    if paper.pdf_path and Path(paper.pdf_path).exists():
        attachments_dir = vault / "attachments" / str(year)
        attachments_dir.mkdir(parents=True, exist_ok=True)
        dest_name = (f"{paper.sha256[:8]}_{safe_title}.pdf"
                     if paper.sha256 else f"{safe_title}.pdf")
        dest_path = attachments_dir / dest_name
        # PDF 중복 검사: 같은 파일이 이미 있으면 건너뛰기
        if dest_path.exists():
            try:
                existing_hash = hashlib.sha256(dest_path.read_bytes()).hexdigest()
                new_hash = hashlib.sha256(Path(paper.pdf_path).read_bytes()).hexdigest()
                if existing_hash == new_hash:
                    print(f"  [PDF] raw PDF 이미 존재 (동일): {dest_path}")
                    raw_rel_path = f"attachments/{year}/{dest_name}"
                else:
                    print(f"  [WARN] PDF 파일명 충돌, 다른 내용: {dest_path}")
            except Exception:
                pass
        else:
            try:
                shutil.copy2(paper.pdf_path, dest_path)
                print(f"  [PDF] raw PDF 복사: {dest_path}")
                raw_rel_path = f"attachments/{year}/{dest_name}"
            except Exception as e:
                print(f"  [WARN] raw PDF 복사 실패 (저장 계속): {e}")
    paper.raw_path = raw_rel_path

    # ── Gap d: 고유 파일명 ──────────────────────────────────────
    inbox_dir = vault / "Inbox" / str(year)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    
    # SHA256이 없고 같은 제목의 기존 노트가 DOI가 다르면 덮어쓰기 방지 위해 suffix 추가
    base_path = inbox_dir / f"{safe_title}.md"
    file_path = get_unique_filepath(base_path, paper.sha256)
    
    # 추가 보호: SHA256이 없지만 같은 제목으로 다른 DOI 노트가 존재하는 경우
    if not paper.sha256 and file_path == base_path and file_path.exists():
        existing_doi_match = _find_existing_note_with_doi(vault, str(year), safe_title, paper.doi)
        if existing_doi_match is None:
            # 같은 제목으로 다른 DOI의 노트가 있으면 suffix 추가
            counter = 2
            while (inbox_dir / f"{safe_title}_{counter}.md").exists():
                counter += 1
            file_path = inbox_dir / f"{safe_title}_{counter}.md"

    # ── 중복 검사 (이중 방어) ────────────────────────────────────
    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8", errors="replace")
        if (paper.sha256 and f'sha256: "{paper.sha256}"' in existing) or (
            paper.doi and f'doi: "{paper.doi}"' in existing
        ):
            print(f"[SKIP] 중복 발견 — 스킵: {file_path}")
            return None
        # 다른 내용인데 같은 파일명이면(충돌) — 안전하게 건너뛰기
        print(f"[SKIP] 파일명 충돌로 스킵: {file_path}")
        return None

    # ── 프론트매터 (백링크 포함) ────────────────────────────────
    fm = build_obsidian_frontmatter(
        paper, verification, passages,
        source_doi=source_doi, source_title=source_title,
    )

    # ── 본문 ────────────────────────────────────────────────────
    body_parts = [fm, "", f"# {paper.title}", ""]
    if paper.authors:
        body_parts.append(f"**저자**: {', '.join(paper.authors)}")
    body_parts.append(f"**DOI**: {paper.doi or 'N/A'}")
    body_parts.append(f"**연도**: {paper.year or 'N/A'}")
    body_parts.append(f"**소스**: {paper.source}")
    body_parts.append("")

    # scite 검증 결과
    body_parts.append("## scite 검증 결과")
    body_parts.append("| 지표 | 값 |")
    body_parts.append("|------|-----|")
    body_parts.append(f"| 검증 상태 | `{verification.verification_status}` |")
    body_parts.append(f"| 라벨 | `{verification.label}` |")
    body_parts.append(f"| 총 인용 | {verification.total_citations} |")
    body_parts.append(f"| Supporting | {verification.supporting} |")
    body_parts.append(f"| Mentioning | {verification.mentioning} |")
    body_parts.append(f"| Contrasting | {verification.contrasting} |")
    if verification.retraction_status:
        body_parts.append(f"| retraction | `{verification.retraction_status}` |")
    body_parts.append("")

    # 원본 raw PDF 위키링크
    if raw_rel_path:
        body_parts.append(f"**원문 PDF**: ![[{raw_rel_path}]]")
        body_parts.append("")

    # evidence snippet
    if verification.evidence_snippets:
        body_parts.append("### Evidence Snippets")
        for i, ev in enumerate(verification.evidence_snippets, 1):
            ctx = (ev.get("context", "") or "")[:200]
            body_parts.append(f"**[{i}]** ({ev.get('type', '')}): _{ctx}_")
        body_parts.append("")

    # 필터링 passage 또는 초록
    if passages:
        body_parts.append("## 유사 전개 필터링 결과")
        body_parts.append(f"threshold: 0.40 | max: {len(passages)} passages")
        body_parts.append("")
        for i, p in enumerate(passages, 1):
            body_parts.append(f"### Passage {i} [{p.section}] (score={p.score})")
            body_parts.append(p.text)
            body_parts.append("")
    elif paper.abstract:
        body_parts.append("## 초록 (abstract)")
        body_parts.append(paper.abstract)

    # ── 원자적 저장 (임시 파일 → rename) ───────────────────────────
    content = "\n".join(body_parts)
    tmp_path = file_path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(file_path)
    invalidate_sha256_cache(vault)
    print(f"[SAVE] 저장 완료: {file_path}")
    return file_path


# ── SHA256 사전 스캔 (Gap b: O(n) → O(1)) ─────────────────────────────

_vault_sha256_cache: dict[str, set[str]] = {}


def build_sha256_set(vault_path: str | Path) -> set[str]:
    """
    Obsidian vault 내 모든 .md의 SHA256을 1회 스캔 후 set 반환.
    n건 .md를 rglob 1회, 각 파일을 1회 읽음. 이후 check_existing_sha256_cached는 O(1).
    """
    vault = Path(vault_path)
    if not vault.exists():
        return set()

    key = str(vault.resolve())
    if key in _vault_sha256_cache:
        return _vault_sha256_cache[key]

    sha256s: set[str] = set()
    md_files = list(vault.rglob("*.md"))
    print(f"[Vault] SHA256 사전 스캔 중: {len(md_files)}개 .md → rglob 완료")

    for md_file in md_files:
        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'sha256:\s*"([a-f0-9]{64})"', text):
                sha256s.add(m.group(1))
        except Exception:
            continue

    _vault_sha256_cache[key] = sha256s
    print(f"[Vault] SHA256 사전 스캔 완료: {len(sha256s)}건 고유 해시 적재")
    return sha256s


def check_existing_sha256_cached(sha256: str, vault_path: str | Path) -> bool:
    """vault SHA256 사전 스캔 set 기반 O(1) 중복 조회."""
    if not sha256:
        return False
    return sha256 in build_sha256_set(vault_path)


def invalidate_sha256_cache(vault_path: str | Path) -> None:
    """vault SHA256 캐시 무효화 (저장 후 호출)."""
    key = str(Path(vault_path).resolve())
    _vault_sha256_cache.pop(key, None)


def write_run_log(
    *,
    doi: Optional[str],
    title: str,
    threshold: float,
    max_passages: int,
    kept: int,
    needs_review: int,
    verification_status: str,
    saved_path: Optional[str],
) -> None:
    """매 실행 inclusion 기준 스냅샷을 SKILL_ROOT/log.md에 append (실패해도 계속)."""
    try:
        log_path = SKILL_ROOT / "log.md"
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        line = (
            f"## [{ts}] citation-pipeline | "
            f"doi={doi or 'N/A'} | title={(title or '')[:60]} | "
            f"threshold={threshold} max_passages={max_passages} | "
            f"kept={kept} needs_review={needs_review} | "
            f"verification={verification_status} | saved={saved_path or 'none'}\n"
        )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"[log] 스냅샷 기록 실패 (계속): {e}", file=sys.stderr)


# ── 메인 파이프라인 ─────────────────────────────────────────────────

async def run_pipeline(
    doi: Optional[str] = None,
    title: Optional[str] = None,
    research_question: str = "",
    vault_path: Optional[str] = None,
    max_citing: int = 50,
    filter_threshold: float = 0.40,
    max_passages: int = 10,
    mailto: str = "",
) -> dict[str, Any]:
    """
    전체 파이프라인 6단계 실행.

    Returns:
        {"status": str, "paper": dict, "verification": dict, "passages": list, "saved_path": str|None}
    """
    print(f"\n{'='*60}")
    print(f"[START] 파이프라인 시작 — DOI: {doi or 'N/A'}, 제목: {title or 'N/A'}")
    print(f"{'='*60}\n")

    # ── ① 정준화 ───────────────────────────────────────────────────
    paper = canonicalize_paper(CanonicalPaper(doi=doi, title=title or ""))

    # ── ③ OpenAlex 보강 ────────────────────────────────────────────
    paper = await enrich_paper(paper)
    print(f"[①-③] OpenAlex 보강 완료: {(paper.title or '')[:60]}")

    # ── ④ 3-tier 본문 확보 ─────────────────────────────────────────
    paper = await acquire_body(paper)
    print(f"[④] 본문 확보 완료: tier={paper.acquisition_tier}, method={paper.acquisition_method}")

    # ── ⑤ 텍스트 추출 + 필터 ───────────────────────────────────────
    passages: list[FilteredPassage] = []
    review_passages: list[FilteredPassage] = []
    if paper.sha256 and research_question:
        all_passages = await extract_and_filter(
            paper, research_question, filter_threshold, max_passages,
            include_review=True,
        )
        passages = [p for p in all_passages if p.filter_verdict == "kept"]
        review_passages = [p for p in all_passages if p.filter_verdict == "needs_human_review"]
        print(f"[⑤] 필터링 통과: {len(passages)}개 kept, {len(review_passages)}개 review")
    else:
        print("[⑤] PDF 없음 또는 RQ 미지정 — 패스")

    # ── ② 인용 논문 수집 (⑥ 교차검증용 DOI 확보) ─────────────────────
    citing_papers: list[dict] = []
    if paper.title:
        citing_papers = dedupe_papers(await collect_scholar_cited_by(paper.title, max_citing, mailto))
        print(f"[②] 인용 논문 수집: {len(citing_papers)}건 (dedupe 후)")

    # ── ⑥ scite 검증 ───────────────────────────────────────────────
    citing_dois = [c.get("doi") for c in citing_papers if c.get("doi")]
    verification = SciteVerification(doi=paper.doi or "", title=paper.title)
    if paper.doi:
        token = load_env_key("SCITE_ACCESS_TOKEN")
        if token:
            verification = await _verify_scite_async(paper.doi, paper.title, token, citing_dois=citing_dois)
        else:
            verification.error = "SCITE_ACCESS_TOKEN 없음"
            verification.verification_status = "scite_unreachable"
        print(f"[⑥] scite 검증: label={verification.label}, status={verification.verification_status}")
        if verification.unconfirmed_by_scite:
            print(f"    └ unconfirmed_by_scite: {len(verification.unconfirmed_by_scite)}건")
    else:
        verification.error = "DOI 없음 — scite 검증 불가"
        verification.verification_status = "unverifiable_no_doi"
        print("[⑥] DOI 없음 — scite 검증 스킵")

    # ── Obsidian 저장 ──────────────────────────────────────────────
    saved_path: Optional[str] = None
    if vault_path:
        # SHA256 사전 스캔 기반 O(1) 중복 검사
        if paper.sha256 and check_existing_sha256_cached(paper.sha256, vault_path):
            print(f"[WARN] SHA256 중복 — 저장 스킵: {paper.sha256[:16]}...")
        else:
            saved = save_to_obsidian(
                paper, verification, passages, vault_path,
                source_doi=None, source_title=None,  # 단일 논문 저장 — 백링크 불필요
            )
            if saved:
                saved_path = str(saved)
    else:
        print("[INFO] vault 경로 미지정 — Obsidian 저장 건너뜀")

    stats = {
        "collected": len(citing_papers),
        "deduped": len(citing_papers),
        "with_doi": sum(1 for c in citing_papers if c.get("doi")) + (1 if paper.doi else 0),
        "with_pdf": 1 if paper.sha256 else 0,
        "verified": 1 if verification.verification_status == "verified" else 0,
        "needs_review": len(review_passages),
        "retracted_flagged": 1 if verification.retraction_status else 0,
        "unconfirmed_by_scite": len(verification.unconfirmed_by_scite),
    }

    write_run_log(
        doi=paper.doi, title=paper.title, threshold=filter_threshold,
        max_passages=max_passages, kept=len(passages),
        needs_review=len(review_passages),
        verification_status=verification.verification_status,
        saved_path=saved_path,
    )

    return {
        "status": "done",
        "paper": asdict(paper),
        "verification": asdict(verification),
        "passages": [asdict(p) for p in passages],
        "review_passages": [asdict(p) for p in review_passages],
        "citing_papers": citing_papers,
        "stats": stats,
        "saved_path": saved_path,
    }


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="논문 수집 → scite 검증 → Obsidian 저장 파이프라인")
    parser.add_argument("--doi", help="논문 DOI (예: 10.18653/v1/N19-1423)")
    parser.add_argument("--title", help="논문 제목 (DOI 없을 때 사용)")
    parser.add_argument("--rq", default="", help="유사 판별 기준 연구 질문")
    parser.add_argument("--vault", help="Obsidian vault 경로 (예: D:/Obsidian Vault)")
    parser.add_argument("--max-citing", type=int, default=50, help="최대 인용 논문 수 (기본 50)")
    parser.add_argument("--threshold", type=float, default=0.40, help="LLM 필터 threshold (기본 0.40)")
    parser.add_argument("--max-passages", type=int, default=10, help="최대 passage 수 (기본 10)")
    parser.add_argument("--mailto", default="", help="OpenAlex polite pool 이메일")
    args = parser.parse_args()

    if not args.doi and not args.title:
        parser.error("--doi 또는 --title 중 하나는 필수입니다.")

    result = asyncio.run(run_pipeline(
        doi=args.doi,
        title=args.title,
        research_question=args.rq,
        vault_path=args.vault,
        max_citing=args.max_citing,
        filter_threshold=args.threshold,
        max_passages=args.max_passages,
        mailto=args.mailto,
    ))

    print(f"\n{'='*60}")
    print(f"[DONE] 파이프라인 완료 — status: {result['status']}")
    print(f"   저장 경로: {result['saved_path'] or '없음'}")
    print(f"   인용 논문: {len(result['citing_papers'])}건")
    print(f"{'='*60}\n")

    # JSON 요약 출력
    summary = {
        "doi": result["paper"]["doi"],
        "title": result["paper"]["title"],
        "year": result["paper"]["year"],
        "acquisition": result["paper"]["acquisition_method"],
        "tier": result["paper"]["acquisition_tier"],
        "sha256": result["paper"]["sha256"],
        "scite_label": result["verification"]["label"],
        "scite_status": result["verification"]["verification_status"],
        "passages": len(result["passages"]),
        "needs_review": result["stats"]["needs_review"],
        "citing_papers": len(result["citing_papers"]),
        "saved": result["saved_path"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
