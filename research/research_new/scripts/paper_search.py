#!/usr/bin/env python3
"""
PubMed + bioRxiv + Semantic Scholar + Springer Nature Open Access 통합 논문 검색 모듈.

각 출처에서 키워드로 최신 논문을 검색하고,
오늘(또는 어제) 업로드된 논문만 필터링하여 반환한다.

PubMed:      eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
bioRxiv:     api.biorxiv.org/details/biorxiv/{start}/{end}/{cursor}/{limit}
SS:          api.semanticscholar.org/graph/v1/paper/search
Springer:    api.springernature.com/openaccess/json
Elsevier:    api.elsevier.com/content/metadata/article
"""

import os
import re
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

import requests
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
# 데이터 모델
# ------------------------------------------------------------------

@dataclass
class Paper:
    """정규화된 논문 메타데이터."""
    source: str        # "pubmed" | "biorxiv" | "semantic_scholar"
    paper_id: str      # PubMed PMID / bioRxiv DOI / SS paper_id
    title: str
    url: str           # 상세 페이지 URL
    abstract: str      # 초록 (요약용)
    authors: List[str] = field(default_factory=list)
    published_date: str = ""  # ISO 8601 문자열
    keywords: List[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)  # 원본 응답 (이미지 URL 등 추출용)


# ------------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------------

def _today_iso() -> str:
    """UTC 기준 오늘 날짜 (YYYY-MM-DD)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_days_ago(days: int) -> str:
    """UTC 기준 days일전 날짜 (YYYY-MM-DD)."""
    d = datetime.now(timezone.utc) - timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def _retry_after(response, default_seconds: int) -> int:
    """
    Retry-After 헤더 안전 파싱.

    - 초 단위 정수면 그대로 사용
    - HTTP-date 포맷 등 파싱 불가한 값은 default_seconds 반환 (ValueError 방지)
    """
    raw = response.headers.get("Retry-After", "") if response is not None else ""
    try:
        seconds = int(str(raw).strip())
        if seconds >= 0:
            return seconds
    except (TypeError, ValueError):
        pass
    return default_seconds


def _fetch_openalex_abstract(doi: str) -> str:
    """OpenAlex 폴백: abstract_inverted_index를 원문 순서로 재조립. 키 불필요(무료)."""
    if not doi:
        return ""
    try:
        r = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}",
                         headers={"Accept": "application/json"}, timeout=20)
        if r.status_code != 200:
            logger.debug(f"[OpenAlex] 초록 조회 실패 (doi={doi}): HTTP {r.status_code}")
            return ""
        inv = (r.json() or {}).get("abstract_inverted_index")
        if not isinstance(inv, dict):
            return ""
        pos = {}
        for word, idxs in inv.items():
            for i in idxs:
                pos[i] = word
        return " ".join(pos[i] for i in sorted(pos))
    except Exception as e:
        logger.debug(f"[OpenAlex] 초록 조회 예외 (doi={doi}): {e}")
        return ""


def _fetch_crossref_abstract(doi: str) -> str:
    """Crossref 폴백: DOI로 초록 조회(JATS 태그 제거). 키 불필요(무료)."""
    if not doi:
        return ""
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}",
                         headers={"Accept": "application/json"}, timeout=20)
        if r.status_code != 200:
            logger.debug(f"[Crossref] 초록 조회 실패 (doi={doi}): HTTP {r.status_code}")
            return ""
        abs_raw = (r.json().get("message", {}) or {}).get("abstract") or ""
        text = re.sub(r"<[^>]+>", " ", abs_raw)
        return " ".join(text.split())
    except Exception as e:
        logger.debug(f"[Crossref] 초록 조회 예외 (doi={doi}): {e}")
        return ""


def _fetch_sd_abstract(pii: str, api_key: str) -> str:
    """Elsevier Abstract Retrieval(META view)로 초록 조회.

    전문(Article Retrieval) 및 FULL view는 별도 엔타이틀먼트 필요(401/403)이므로,
    무료로 열려 있는 META의 dc:description만 시도한다. 실패 시 "".
    """
    url = f"https://api.elsevier.com/content/abstract/pii/{pii}"
    headers = {"Accept": "application/json", "X-ELS-APIKey": api_key}
    insttoken = os.getenv("ELSEVIER_INST_TOKEN", "").strip()
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    try:
        r = requests.get(url, params={"httpAccept": "application/json", "view": "META"},
                         headers=headers, timeout=30)
        if r.status_code != 200:
            logger.debug(f"[Elsevier] 초록 조회 실패 (pii={pii}): HTTP {r.status_code}")
            return ""
        core = r.json().get("abstracts-retrieval-response", {}).get("coredata", {})
        return (core.get("dc:description") or "").strip()
    except Exception as e:
        logger.debug(f"[Elsevier] 초록 조회 예외 (pii={pii}): {e}")
        return ""


# ------------------------------------------------------------------
# PubMed
# ------------------------------------------------------------------

def search_pubmed(query: str, max_results: int = 5, lookback_days: int = 1) -> List[Paper]:
    """
    PubMed에서 검색어로 논문을 검색.

    - reldate=lookback_days + datetype=pudate (발표일 기준)
    - UTC 기준이므로 KST 어제 발간물도 포함됨.
    - 상세 메타데이터는 efetch.fcgi로 별도 조회.
    """
    base_search = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    base_fetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    # 1. ID 검색 (발표일 필터)
    search_params = {
        "db": "pubmed",
        "term": query,
        "reldate": str(lookback_days),
        "datetype": "pdat",
        "retmode": "json",
        "retmax": str(max_results),
    }

    try:
        r = requests.get(base_search, params=search_params, timeout=30)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        logger.error(f"[PubMed] esearch 실패: {e}")
        return []

    if not ids:
        logger.info("[PubMed] 결과 없음")
        return []

    # 2. 메타데이터 fetch (esummary)
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "json",
    }
    try:
        r2 = requests.get(base_fetch, params=fetch_params, timeout=30)
        r2.raise_for_status()
        summary = r2.json().get("result", {})
    except Exception as e:
        logger.error(f"[PubMed] esummary 실패: {e}")
        return []

    # 3. 초록 fetch (esummary은 초록을 반환하지 않으므로 efetch 사용)
    abstracts = _fetch_pubmed_abstracts(ids)

    papers: List[Paper] = []
    for pmid in ids:
        info = summary.get(pmid, {})
        if not info:
            continue
        pub_date = info.get("pubdate", "")  # "2024/08/19"
        title = info.get("title", "")
        authors = [a.get("name", "") for a in info.get("authors", [])]
        abstract = abstracts.get(pmid, "")

        papers.append(Paper(
            source="pubmed",
            paper_id=pmid,
            title=title,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            abstract=abstract,
            authors=authors,
            published_date=pub_date,
            raw=info,
        ))

    logger.info(f"[PubMed] {len(papers)}건 검색 (lookback={lookback_days}일)")
    return papers


def _fetch_pubmed_abstracts(ids: List[str]) -> Dict[str, str]:
    """
    PubMed 초록을 efetch.fcgi로 조회.

    esummary은 초록 텍스트를 반환하지 않으므로, efetch(retmode=xml)로
    각 PMID별 AbstractText를 추출한다. itertext()로 중첩 태그(<b> 등)까지
    수집하고 연속 공백을 정규화한다.
    """
    if not ids:
        return {}

    base_efetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    try:
        r = requests.get(base_efetch, params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception as e:
        logger.error(f"[PubMed] efetch 실패: {e}")
        return {}

    abstracts: Dict[str, str] = {}
    for article in root.iter("PubmedArticle"):
        pmid = article.findtext(".//PMID") or ""
        texts = [" ".join(" ".join(t.itertext()).split()) for t in article.iter("AbstractText")]
        text = " ".join(x for x in texts if x)
        if pmid:
            abstracts[pmid] = text.strip()
    return abstracts


# ------------------------------------------------------------------
# bioRxiv
# ------------------------------------------------------------------

def search_biorxiv(query: str, max_results: int = 5, lookback_days: int = 1) -> List[Paper]:
    """
    bioRxiv API로 날짜 범위 내 최근 논문 검색.
    bioRxiv은 키워드 검색 API를 제공하지 않으므로,
    날짜 범위 내 모든 논문을 가져와 클라이언트 측에서 키워드 필터링.

    - API: https://api.biorxiv.org/details/biorxiv/{start}/{end}/{cursor}/{limit}
    - 날짜 범위: lookback_days 일전 ~ 오늘 (UTC)
    - 키워드는 초록/제목에서 클라이언트 측 필터링 (OR 매칭)
    """
    today = _today_iso()
    start_date = _date_days_ago(lookback_days)

    # 검색어 조건 파싱:
    # 1) '&'로 구분된 각 텀은 모두 만족해야 함 (AND 조건)
    # 2) 각 텀 내부의 단어들도 모두 포함되거나 전체 구문이 일치해야 함 (단어 경계 \b 매칭)
    #    (예: "maternal immune activation"에서 "activation" 단독 매칭으로 인한 오탐 차단)
    query_lower = query.lower().strip()
    and_blocks = [b.strip() for b in query_lower.split("&") if b.strip()]

    def _matches_block(block: str, text: str) -> bool:
        if not block:
            return True
        if block in text:
            return True
        words = block.split()
        if not words:
            return True
        return all(bool(re.search(rf"\b{re.escape(w)}\b", text)) for w in words)

    headers = {"Accept": "application/json"}

    # API 페이지 크기는 고정 (max_results에 비례시키면 cursor 가드와 결합해
    # 단일 페이지만 스캔하는 문제가 생김). 최대 max_pages 페이지까지 스캔.
    page_size = 100
    max_pages = 3

    all_papers: List[Paper] = []
    cursor = 0
    for _page in range(max_pages):
        url = f"https://api.biorxiv.org/details/biorxiv/{start_date}/{today}/{cursor}/{page_size}"
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 404:
                break
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"[bioRxiv] 검색 실패: {e}")
            break

        collection = data.get("collection", [])
        if not collection:
            break

        for item in collection:
            title = item.get("title", "")
            abstract = item.get("abstract", "") or ""
            combined = (title + " " + abstract).lower()

            # 모든 and_block 조건을 충족해야 통과 (단어 경계 및 AND 매칭)
            if and_blocks and not all(_matches_block(b, combined) for b in and_blocks):
                continue

            authors_str = item.get("authors", "")
            authors = [a.strip() for a in authors_str.split(";") if a.strip()] if authors_str else []
            doi = item.get("doi", "")
            date_str = item.get("date", "")
            biorxiv_url = item.get("url", "")
            if not biorxiv_url:
                biorxiv_id = item.get("id", "")
                biorxiv_url = f"https://www.biorxiv.org/content/{date_str}/{biorxiv_id}"
            if not biorxiv_url.startswith("http"):
                # bioRxiv ID로 URL 구성
                biorxiv_id = item.get("id", "")
                biorxiv_url = f"https://www.biorxiv.org/content/{date_str}/{biorxiv_id}"

            all_papers.append(Paper(
                source="biorxiv",
                paper_id=doi or item.get("id", ""),
                title=title,
                url=biorxiv_url,
                abstract=abstract,
                authors=authors,
                published_date=date_str,
                raw=item,
            ))

            if len(all_papers) >= max_results:
                break

        if len(all_papers) >= max_results:
            break

        cursor += page_size
        if len(collection) < page_size:
            break  # 더 이상 결과 없음

    logger.info(f"[bioRxiv] {len(all_papers)}건 검색 (lookback={lookback_days}일, date range: {start_date}~{today})")
    return all_papers[:max_results]


# ------------------------------------------------------------------
# Semantic Scholar
# ------------------------------------------------------------------

def search_semantic_scholar(
    query: str, max_results: int = 5
) -> List[Paper]:
    """
    Semantic Scholar Graph API로 검색.

    - 무료: 1req/s, API key 없음
    - 반환 필드: title, url, authors, year, abstract, publicationDate
    """
    base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": str(max_results),
        # venue/citationCount: IF 미지정 저널의 영향력 보정용 (_impact_score)
        "fields": "title,url,authors,year,abstract,publicationDate,openAccessPdf,citationCount,venue",
    }
    headers = {
        "Accept": "application/json",
    }

    try:
        max_api_retries = 3
        for attempt in range(max_api_retries):
            r = requests.get(base_url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                retry_after = _retry_after(r, 2 + attempt * 3)
                logger.warning(f"[Semantic Scholar] Rate limited (429). {retry_after}s 대기 후 재시도 ({attempt+1}/{max_api_retries})...")
                time.sleep(retry_after)
                continue
            if r.status_code == 500:
                if attempt < max_api_retries - 1:
                    logger.warning(f"[Semantic Scholar] Server Error (500). 재시도 ({attempt+1}/{max_api_retries})...")
                    time.sleep(2 + attempt * 3)
                    continue
            r.raise_for_status()
            data = r.json()
            break
        else:
            logger.error("[Semantic Scholar] 모든 재시도 실패")
            return []
    except requests.exceptions.ConnectionError:
        logger.error(f"[Semantic Scholar] 연결 실패")
        return []
    except Exception as e:
        logger.error(f"[Semantic Scholar] 검색 실패: {e}")
        return []

    papers: List[Paper] = []
    for p in data.get("data", []):
        paper_id = p.get("paperId", "")
        title = p.get("title", "")
        url = p.get("url", "")
        abstract = p.get("abstract", "") or ""
        authors = [a.get("name", "") for a in p.get("authors", [])]
        pub_date = p.get("publicationDate", "") or ""
        year = p.get("year", "")
        oa_pdf = (p.get("openAccessPdf") or {}).get("url", "")

        papers.append(Paper(
            source="semantic_scholar",
            paper_id=paper_id,
            title=title,
            url=url,
            abstract=abstract,
            authors=authors,
            published_date=(pub_date or (str(year) if year else "")),
            raw={
                "pdf_url": oa_pdf,
                "year": year,
                "paperId": paper_id,
                "venue": p.get("venue") or "",
                "citationCount": p.get("citationCount") or 0,
            },
        ))

    logger.info(f"[Semantic Scholar] {len(papers)}건 검색")
    return papers


# ------------------------------------------------------------------
# Springer Nature Open Access API
# ------------------------------------------------------------------

def search_springer(
    query: str,
    max_results: int = 5,
    api_key: str = None,
) -> List[Paper]:
    """
    Springer Nature Open Access API로 검색.

    - API: https://api.springernature.com/openaccess/json
    - 쿼리 형식: q=keyword:<검색어> (예: q=keyword%3A%20test)
    - 인증: api_key를 쿼리 파라미터로 전달 (헤더 아님)
    - 제한: 500 Hits/Day (Daily Quota), 100 Hits/Min (Throttling)
    - API key: .env의 SPRINGER_API_KEY 또는 인자로 전달
    """
    if api_key is None:
        api_key = os.getenv("SPRINGER_API_KEY", "")

    if not api_key:
        logger.warning("[Springer] API key 없음 - 검색 건너뜀")
        return []

    base_url = "https://api.springernature.com/openaccess/json"
    # 키워드 내 &는 space로 치환해서 파싱 안정화 (예: "autism&macrophage" → "autism macrophage")
    clean_query = query.replace("&", " ").strip()
    # Springer API는 아포스트로피를 포함한 쿼리에서 404를 반환할 수 있으므로,
    # 검색어 내 '를 제거하여 안정화 (예: "alzheimer's disease" → "alzheimers disease")
    clean_query = clean_query.replace("'", "")
    params = {
        "api_key": api_key,
        "q": f"keyword: {clean_query}",
        "s": 1,
        "p": str(max_results),
    }
    headers = {"Accept": "application/json"}

    # Rate limit 대응: 100 Hits/Min = 1req/0.6s → 최소 0.7초 대기
    max_api_retries = 3
    used_fallback = False
    for attempt in range(max_api_retries):
        try:
            r = requests.get(base_url, params=params, headers=headers, timeout=60)
            if r.status_code == 429:
                retry_after = _retry_after(r, 60)
                logger.warning(f"[Springer] Rate limited (429). {retry_after}s 대기 후 재시도 ({attempt+1}/{max_api_retries})...")
                time.sleep(retry_after)
                continue
            if r.status_code == 403:
                logger.warning("[Springer] API key 오류 (403) - 무효 또는 할당량 초과")
                return []
            if r.status_code == 401:
                logger.warning("[Springer] API key 오류 (401) - 무효 또는 할당량 초과")
                return []
            if r.status_code == 404:
                # keyword: 필드 검색은 용어 미일치 시 404를 반환할 수 있음.
                # 평문 쿼리로 한 번 재시도하고, 그래도 없으면 빈 결과로 처리.
                if not used_fallback:
                    used_fallback = True
                    params = {k: v for k, v in params.items() if k != "q"}
                    params["q"] = clean_query
                    logger.info(f"[Springer] 404 → 평문 검색으로 재시도: {clean_query!r}")
                    continue
                logger.info(f"[Springer] 검색 결과 없음 (404): {clean_query!r}")
                return []
            if r.status_code == 500:
                if attempt < max_api_retries - 1:
                    logger.warning(f"[Springer] Server Error (500). 재시도 ({attempt+1}/{max_api_retries})...")
                    time.sleep(2 + attempt * 3)
                    continue
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            err = str(e)
            if api_key:
                err = err.replace(api_key, "***")  # URL에 api_key 쿼리 포함 — 로그 유출 방지
            logger.error(f"[Springer] 검색 실패: {err}")
            if attempt < max_api_retries - 1:
                time.sleep(2 + attempt * 3)
                continue
            return []
    else:
        # 모든 재시도가 429 continue로 소진된 경우: data 미할당 NameError 방지
        logger.error("[Springer] 모든 재시도 실패 (rate limit)")
        return []

    papers: List[Paper] = []
    for entry in data.get("records", []):
        paper_id = entry.get("doi", "") or entry.get("identifier", "")
        title = entry.get("title", "")
        # URL: Springer 응답은 {"url": [{"format":..., "platform":..., "value": "..."}]}
        # 형태이므로 첫 항목의 value를 추출, 없으면 DOI 링크로 fallback
        raw_url = entry.get("url", "")
        url = ""
        if isinstance(raw_url, list) and raw_url:
            for u in raw_url:
                if isinstance(u, dict):
                    v = u.get("value", "") or u.get("url", "")
                    if v:
                        url = v
                        break
        if not url and isinstance(raw_url, dict):
            url = raw_url.get("value", "") or raw_url.get("url", "")
        if not url and paper_id:
            url = f"https://doi.org/{paper_id}"
        # Springer 응답은 abstract가 dict 형태 {"h1": "Abstract", "p": [...]}일 수 있음.
        # p는 문자열 리스트(문단) 또는 문자 리스트(단어) 모두 올 수 있어 타입별로 처리.
        abstract_raw = entry.get("abstract", "")
        abstract = ""
        if isinstance(abstract_raw, dict):
            p = abstract_raw.get("p", "")
            if isinstance(p, str):
                abstract = p.strip()
            elif isinstance(p, list):
                # 원소가 단어/문단 문자열이면 그대로, 문자 단위 리스트면 공백 없이 결합
                abstract = "".join(str(x) for x in p).strip()
        elif isinstance(abstract_raw, str):
            abstract = abstract_raw.strip()
        abstract = abstract or ""
        # 저자: Springer 응답은 {"creators": [{"creator": "Name", ...}]} 형태
        # 각 항목의 "creator" 필드 값을 추출 (ORCID 등 다른 키 무시)
        authors = []
        creators = entry.get("creators", [])
        if isinstance(creators, list):
            for a in creators:
                if isinstance(a, dict):
                    name = a.get("creator", "") or a.get("name", "")
                    if name:
                        authors.append(name)
        elif isinstance(creators, dict):
            name = creators.get("creator", "") or creators.get("name", "")
            if name:
                authors.append(name)
        # publicationDate 필드 사용 (datePublished 아님)
        pub_date = entry.get("publicationDate", "") or entry.get("datePublished", "")

        papers.append(Paper(
            source="springer",
            paper_id=paper_id,
            title=title,
            url=url,
            abstract=abstract,
            authors=authors,
            published_date=pub_date,
            raw=entry,
        ))

    logger.info(f"[Springer] {len(papers)}건 검색")
    return papers


# ------------------------------------------------------------------
# Elsevier (Scopus / ScienceDirect) — elsapy API
# ------------------------------------------------------------------

def search_elsevier(query: str, max_results: int = 5, api_key: str = None) -> List[Paper]:
    """
    Elsevier ScienceDirect Search API V2로 검색.

    - Endpoint: https://api.elsevier.com/content/search/sciencedirect
      (구 /content/metadata/article의 COMPLETE view는 엔타이틀먼트가 없으면 401/빈 결과.
       ScienceDirect는 WADL 기준 STANDARD view만 허용 — 초록은 별도 보강)
    - 인증: X-ELS-APIKey 헤더 (+ 선택 ELSEVIER_INST_TOKEN → X-ELS-Insttoken)
    - Query: Boolean search. count 허용값 10/25/50/100 → 요청값을 최소 허용값으로 올림
    - 초록 보강: Abstract Retrieval(META, PII) → Crossref(DOI) → OpenAlex(DOI)
      (ELSEVIER_SKIP_ABSTRACT_ENRICH=1 로 비활성)
    - 제한: 100 Hits/Min (Throttling)
    - API key: .env의 ELSEVIER_API_KEY 또는 인자로 전달
    """
    if api_key is None:
        api_key = os.getenv("ELSEVIER_API_KEY", "")

    if not api_key:
        logger.warning("[Elsevier] API key 없음 - 검색 건너뜀")
        return []

    base_url = "https://api.elsevier.com/content/search/sciencedirect"
    # WADL: count 허용 10,25,50,100 — 그 외 값(예: 2,5)은 최소 허용값으로 올림
    allowed_counts = (10, 25, 50, 100)
    count_val = max_results
    if count_val not in allowed_counts:
        for a in allowed_counts:
            if a >= count_val:
                count_val = a
                break
        else:
            count_val = 100
    params = {
        "query": query,
        "count": str(count_val),
        "start": "0",
        "view": "STANDARD",
    }
    headers = {
        "Accept": "application/json",
        "X-ELS-APIKey": api_key,
    }
    # 기관 토큰(원격/프록시 환경). WADL: X-ELS-Insttoken / insttoken
    insttoken = os.getenv("ELSEVIER_INST_TOKEN", "").strip()
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken

    max_api_retries = 3
    for attempt in range(max_api_retries):
        try:
            r = requests.get(base_url, params=params, headers=headers, timeout=60)
            if r.status_code == 429:
                retry_after = _retry_after(r, 60)
                logger.warning(
                    f"[Elsevier] Rate limited (429). {retry_after}s 대기 후 "
                    f"재시도 ({attempt+1}/{max_api_retries})..."
                )
                time.sleep(retry_after)
                continue
            if r.status_code == 401:
                logger.warning("[Elsevier] API key 오류 (401) - 무효 (X-ELS-APIKey/apiKey 확인)")
                return []
            if r.status_code == 403:
                logger.warning("[Elsevier] 권한/구독 오류 (403) - 기관 IP/Insttoken 또는 VIEW 권한 확인")
                return []
            if r.status_code == 500:
                if attempt < max_api_retries - 1:
                    logger.warning(
                        f"[Elsevier] Server Error (500). 재시도 "
                        f"({attempt+1}/{max_api_retries})..."
                    )
                    time.sleep(2 + attempt * 3)
                    continue
            r.raise_for_status()
            data = r.json()
            break
        except requests.exceptions.ConnectionError:
            logger.error("[Elsevier] 연결 실패")
            if attempt < max_api_retries - 1:
                time.sleep(2 + attempt * 3)
                continue
            return []
        except Exception as e:
            logger.error(f"[Elsevier] 검색 실패: {e}")
            if attempt < max_api_retries - 1:
                time.sleep(2 + attempt * 3)
                continue
            return []
    else:
        logger.error("[Elsevier] 모든 재시도 실패")
        return []

    papers: List[Paper] = []
    # API 응답 구조: {"search-results": {"entry": [...]}}
    entries = data.get("search-results", {}).get("entry", [])
    # error entry ({"@_fa": "true", "error": "..."}) 제외 + dict만 통과
    entries = [e for e in entries if isinstance(e, dict) and not e.get("error")]
    # WADL count 정규화로 요청보다 많이 올 수 있으므로 먼저 절단(초록 보강 API 비용도 절감)
    entries = entries[:max_results]
    skip_enrich = os.getenv("ELSEVIER_SKIP_ABSTRACT_ENRICH", "").strip() in {"1", "true", "yes"}
    for entry in entries:
        # DOI 우선; link는 @href로 안전 파싱 (@URL 키는 응답에 없음, 빈 리스트 IndexError 방지)
        paper_id = (
            entry.get("prism:doi", "")
            or entry.get("doi", "")
            or entry.get("dc:identifier", "")
            or entry.get("eid", "")
        )
        title = entry.get("dc:title", "") or entry.get("title", "")

        url = entry.get("prism:url", "") or entry.get("URL", "")
        link_list = entry.get("link", [])
        if isinstance(link_list, list):
            for ln in link_list:
                if isinstance(ln, dict) and ln.get("@ref") != "self":
                    href = ln.get("@href", "")
                    if href:
                        url = href
                        break

        abstract = (
            entry.get("dc:description", "")
            or entry.get("dc:abstract", "")
            or entry.get("description", "")
            or entry.get("abstract", "")
        )
        # STANDARD view엔 초록 필드가 없음 → 보강 순서: Abstract Retrieval(META) → Crossref(DOI) → OpenAlex(DOI)
        if not abstract and not skip_enrich:
            _pii = entry.get("pii", "")
            if _pii:
                abstract = _fetch_sd_abstract(_pii, api_key)
            if not abstract:
                _doi = paper_id if str(paper_id).startswith("10.") else ""
                cr = _fetch_crossref_abstract(_doi)
                if cr:
                    abstract = cr
                    entry["abstract_source"] = "crossref"
            if not abstract:
                oa = _fetch_openalex_abstract(_doi)
                if oa:
                    abstract = oa
                    entry["abstract_source"] = "openalex"

        # 저자 추출 — ScienceDirect: authors.author[].$ / Scopus: author[]
        authors = []
        author_list = entry.get("author", [])
        if not author_list and isinstance(entry.get("authors"), dict):
            author_list = entry["authors"].get("author", [])
        if isinstance(author_list, list):
            for a in author_list:
                if isinstance(a, dict):
                    name = a.get("$", a.get("author-name", ""))
                    if name:
                        authors.append(name)
        elif isinstance(author_list, dict):
            name = author_list.get("$", author_list.get("author-name", ""))
            if name:
                authors.append(name)
        if not authors:
            single = entry.get("dc:creator", "")
            if single:
                authors = [single]

        pub_date = (
            entry.get("prism:coverDate", "")
            or entry.get("prism:publishedDate", "")
            or entry.get("dc:date", "")
        )
        # DOI 있으면 사람이 읽는 doi.org 링크로 교체
        if paper_id and str(paper_id).startswith("10."):
            url = f"https://doi.org/{paper_id}"

        papers.append(Paper(
            source="elsevier",
            paper_id=paper_id,
            title=title,
            url=url,
            abstract=abstract,
            authors=authors,
            published_date=pub_date,
            raw=entry,
        ))

    logger.info(f"[Elsevier] {len(papers)}건 중 {min(len(papers), max_results)}건 반환 (WADL count 정규화)")
    return papers[:max_results]


# ------------------------------------------------------------------
# 통합 검색
# ------------------------------------------------------------------

# 주요 생명과학 저널 근사 Impact Factor (순위 산정용 근사치, 매년 변동)
# 키는 _norm_journal()로 정규화된 형태 (소문자, 구두점→공백, & → and)
_IMPACT_FACTOR = {
    "new england journal of medicine": 158,
    "jama": 120,
    "lancet": 98,
    "cell": 64,
    "nature": 50,
    "science": 45,
    "nature medicine": 58,
    "nature reviews immunology": 38,
    "nature reviews neuroscience": 25,
    "nature immunology": 27,
    "immunity": 27,
    "acta neuropathologica": 25,
    "nature neuroscience": 21,
    "nature cell biology": 21,
    "science immunology": 20,
    "science translational medicine": 17,
    "alzheimer s and dementia": 16,
    "neuron": 15,
    "journal of experimental medicine": 15,
    "molecular neurodegeneration": 14,
    "nature communications": 14,
    "pnas": 11,
    "proceedings of the national academy of sciences": 11,
    "brain": 11,
    "molecular psychiatry": 11,
    "biological psychiatry": 10,
    "journal of neuroinflammation": 9,
    "brain behavior and immunity": 8,
    "elife": 7,
    "plos biology": 7,
    "translational psychiatry": 6,
    "molecular autism": 7,
    "glia": 6,
    "cells": 6,
    "autism research": 5,
    "international journal of molecular sciences": 5,
    "journal of immunology": 5,
    "scientific reports": 4,
}


def _norm_journal(name: str) -> str:
    """저널명을 비교 가능한 형태로 정규화 (소문자, 구두점 제거, & → and)."""
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _journal_of(paper: Paper) -> str:
    """소스별 raw 응답에서 저널명 추출 (프리프린트는 빈 문자열)."""
    raw = paper.raw if isinstance(paper.raw, dict) else {}
    if paper.source == "pubmed":
        return raw.get("fulljournalname") or raw.get("source") or ""
    if paper.source == "springer":
        return raw.get("journal_title") or raw.get("containerTitle") or ""
    if paper.source == "elsevier":
        return raw.get("prism:publicationName") or raw.get("prism:journalName") or ""
    if paper.source == "semantic_scholar":
        return raw.get("venue") or ""
    return ""


def _impact_score(paper: Paper) -> float:
    """
    정렬용 영향력 점수.

    - 알려진 저널: 등재된 근사 IF
    - 미지정 저널: 8.0 / 프리프린트(bioRxiv 등): 5.0
    - 보정: 인용수 100회당 +1 (최대 +10, SS citationCount 등)
    """
    j = _norm_journal(_journal_of(paper))
    base = float(_IMPACT_FACTOR.get(j, 0))
    if base == 0:
        base = 8.0 if j else 5.0
    try:
        cites = int(raw_cites := (paper.raw or {}).get("citationCount") or 0)
    except (TypeError, ValueError):
        cites = 0
    return base + min(10.0, cites / 100.0)


def _select_top_papers(
    buckets: List[List[Paper]], n_topics: int, per_keyword: int = 5
) -> Tuple[List[Paper], List[int]]:
    """
    키워드별 선발 + 부족분 재배분.

    - 키워드마다 IF 점수 상위 per_keyword건 선출
    - 검색 실패/미달 키워드의 남은 몫(per_keyword × n_topics까지)은
      전체 잔여 풀에서 IF 순으로 채움

    Returns: (선발된 논문 목록, 키워드 버킷별 최종 선발 수)
    """
    selected: List[Paper] = []
    leftovers: List[Paper] = []
    taken_per_bucket: List[int] = []

    for bucket in buckets:
        ranked = sorted(bucket, key=_impact_score, reverse=True)
        take = ranked[:per_keyword]
        selected.extend(take)
        leftovers.extend(ranked[per_keyword:])
        taken_per_bucket.append(len(take))

    target = per_keyword * max(n_topics, len(buckets))
    if len(selected) < target:
        leftovers.sort(key=_impact_score, reverse=True)
        refill = leftovers[: target - len(selected)]
        selected.extend(refill)
        # 재배분 분은 출처 버킷을 알 수 없으므로 집계에서 제외 (로그는 키워드별 직접 선발만)
        if leftovers:
            logger.debug(f"[통합] 부족분 재배분 {len(refill)}건 (IF순)")

    return selected, taken_per_bucket

def search_all(
    topic: str,
    max_results: int = 5,
    lookback_days: int = 1,
    per_keyword: int = 5,
    deadline: Optional[float] = None,
) -> List[Paper]:
    """
    모든 출처에서 통합 검색 후 키워드별 선발.
    - deadline: time.monotonic() 기준 검색 마감 시각 (초과 시 즉시 중단 후 수집분으로 진행)
    """
    # 다중 키워드 파싱 (세미콜론 또는 쉼표 구분)
    topics = [t.strip() for t in re.split(r"[;\n,]", topic) if t.strip()]
    if len(topics) == 0:
        topics = [topic.strip()] if topic.strip() else ["all"]

    by_keyword: List[List[Paper]] = []
    bucket_labels: List[str] = []
    seen_titles: set = set()

    def _collect(papers: List[Paper], label: str) -> None:
        """전역 중복 제목 제거 후 해당 키워드 버킷에 추가."""
        bucket = []
        for p in papers:
            key = re.sub(r"[^a-z0-9]+", "", p.title.lower())
            if not key or key in seen_titles:
                continue
            seen_titles.add(key)
            bucket.append(p)
        if bucket:
            by_keyword.append(bucket)
            bucket_labels.append(label)

    for kw in topics:
        if deadline and time.monotonic() > deadline:
            logger.warning(
                f"[통합] 검색 시간 상한 도달 → 남은 키워드 검색 중단 "
                f"(현재 수집된 {sum(len(b) for b in by_keyword)}건으로 선발 진행)"
            )
            break

        # '&'는 Springer 외 소스(API 쿼리스트링/클라이언트 필터)에서 파싱을 깨뜨림 → 공백 치환
        kw_clean = kw.replace("&", " ").strip()
        if not kw_clean:
            continue
        logger.info(f"[통합] 키워드 '{kw}' 검색 중...")

        # 소스별 격리: 한 소스의 예외가 다른 소스 결과를 폐기하지 않도록 함
        bucket_papers: List[Paper] = []

        try:
            bucket_papers.extend(search_pubmed(kw_clean, max_results, lookback_days))
        except Exception as e:
            logger.error(f"[통합] PubMed 실패, 건너뜀: {e}")

        try:
            bucket_papers.extend(search_biorxiv(kw_clean, max_results, lookback_days))
        except Exception as e:
            logger.error(f"[통합] bioRxiv 실패, 건너뜀: {e}")

        try:
            bucket_papers.extend(search_semantic_scholar(kw_clean, max_results))
        except Exception as e:
            logger.error(f"[통합] Semantic Scholar 실패, 건너뜀: {e}")

        try:
            bucket_papers.extend(search_springer(kw_clean, max_results))
        except Exception as e:
            logger.error(f"[통합] Springer 실패, 건너뜀: {e}")

        try:
            bucket_papers.extend(search_elsevier(kw_clean, max_results))
        except Exception as e:
            logger.error(f"[통합] Elsevier 실패, 건너뜀: {e}")

        _collect(bucket_papers, kw_clean)

    n_candidates = sum(len(b) for b in by_keyword)
    selected, taken = _select_top_papers(by_keyword, n_topics=len(topics), per_keyword=per_keyword)

    dist = ", ".join(
        f"{label}={n}" for label, n in zip(bucket_labels, taken)
    )
    logger.info(
        f"[통합] 후보 {n_candidates}건 → 키워드별 상위 {per_keyword}건(IF순) 선발 {len(selected)}건 "
        f"({dist})"
    )
    return selected


# ------------------------------------------------------------------
# CLI / 단독 실행
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    # Windows 콘솔(cp949) 이모지/한글 출력 오류 방지
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    load_dotenv()

    topic = os.getenv("RESEARCH_TOPIC", "Cancer Immunotherapy")
    max_r = int(os.getenv("RESEARCH_MAX_RESULTS", "5"))
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    papers = search_all(topic, max_results=max_r, lookback_days=days)
    for p in papers:
        print(f"\n[{p.source}] {p.title}")
        print(f"  ID: {p.paper_id} | Date: {p.published_date}")
        print(f"  URL: {p.url}")
        print(f"  Abstract: {p.abstract[:200]}...")
        if p.raw.get("pdf_url"):
            print(f"  PDF: {p.raw['pdf_url']}")
        if p.raw.get("landingPageUrl"):
            print(f"  Landing: {p.raw['landingPageUrl']}")
