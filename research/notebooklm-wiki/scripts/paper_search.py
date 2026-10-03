#!/usr/bin/env python3
"""
PubMed + bioRxiv + Semantic Scholar + Springer Nature Open Access 통합 논문 검색 모듈.

각 출처에서 키워드로 최신 논문을 검색하고,
오늘(또는 어제) 업로드된 논문만 필터링하여 반환한다.

PubMed:      eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
bioRxiv:    api.biorxiv.org/details/biorxiv/{start}/{end}/{cursor}/{limit}
SS:          api.semanticscholar.org/graph/v1/paper/search
Springer:    api.springernature.com/openaccess/search
"""

import os
import re
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

import requests

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


def _retry_after_seconds(headers, default: int = 60) -> int:
    """Retry-After 헤더 안전 파싱 — HTTP-date 등 비숫자 값 시 default 반환."""
    v = (headers or {}).get("Retry-After")
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return default


def _fetch_pubmed_abstracts(pmids: List[str]) -> Dict[str, str]:
    """esummary에는 초록이 없으므로 efetch(XML)로 일괄 조회. {pmid: abstract}"""
    if not pmids:
        return {}
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract", "retmode": "xml"}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception as e:
        logger.warning(f"[PubMed] efetch(초록) 조회 실패: {e}")
        return {}
    out: Dict[str, str] = {}
    for art in root.iter("PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        # itertext로 중첩 태그(<b> 등)까지 수집 + 연속 공백 정규화
        texts = [" ".join(" ".join(t.itertext()).split()) for t in art.iter("AbstractText")]
        text = " ".join(x for x in texts if x)
        if pmid:
            out[pmid] = text
    return out


def _fetch_sd_abstract(pii: str, api_key: str) -> str:
    """Abstract Retrieval(META view)로 초록 조회.

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


def _fetch_crossref_abstract(doi: str) -> str:
    """Crossref 폴백: Elsevier 경로로 초록을 못 얻으면 DOI로 조회(JATS 태그 제거).

    키 불필요(무료). Elsevier는 대부분의 논문 초록을 Crossref에 deposit 한다.
    """
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


# ------------------------------------------------------------------
# PubMed
# ------------------------------------------------------------------

def search_pubmed(query: str, max_results: int = 5, lookback_days: int = 1) -> List[Paper]:
    """
    PubMed에서 검색어로 논문을 검색.

    - reldate=lookback_days + datetype=pdat (발표일 기준)
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

    # esummary엔 초록이 없으므로 efetch로 일괄 보강
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

    # 검색어 키워드 (OR 매칭을 위해 분리)
    query_lower = query.lower()
    # "Cancer Immunotherapy" → ["cancer", "immunotherapy"]
    query_terms = [t for t in re.split(r"\s+", query_lower) if t]

    base_url = f"https://api.biorxiv.org/details/biorxiv/{start_date}/{today}/0/{max_results * 20}"
    # max_results * 20: 키워드 필터링 후보를 넉넉히 잡음 (bioRxiv은 30개 페이지 반환)

    headers = {"Accept": "application/json"}

    all_papers: List[Paper] = []
    cursor = 0
    page_size = max_results * 20

    while len(all_papers) < max_results and cursor < 200:  # max 200건 스캔
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

            # OR 매칭: 검색어 중 하나라도 포함되면 통과
            if not any(term in combined for term in query_terms if term):
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
        "fields": "title,url,authors,year,abstract,publicationDate,openAccessPdf",
    }
    headers = {
        "Accept": "application/json",
    }

    try:
        max_api_retries = 3
        for attempt in range(max_api_retries):
            r = requests.get(base_url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                retry_after = _retry_after_seconds(r.headers, default=2 + attempt * 3)
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
            raw={"pdf_url": oa_pdf, "year": year, "paperId": paper_id},
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

    - API: https://api.springernature.com/openaccess/search
    - 쿼리 형식: q="cancer immunotherapy" (따옴표로 정확 매칭)
    - 제한: 500 Hits/Day (Daily Quota), 100 Hits/Min (Throttling)
    - API key: .env의 SPRINGER_API_KEY 또는 인자로 전달
    """
    if api_key is None:
        api_key = os.getenv("SPRINGER_API_KEY", "")

    if not api_key:
        logger.warning("[Springer] API key 없음 - 검색 건너뜀")
        return []

    base_url = "https://api.springernature.com/openaccess/json"
    # 키워드 내 &amp;는 space로 치환해서 파싱 안정화 (예: "autism&amp;macrophage" → "autism macrophage")
    clean_query = query.replace("&amp;", " ").strip()
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
                retry_after = _retry_after_seconds(r.headers)
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
        logger.error("[Springer] 모든 재시도 실패")
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
        # Springer 응답은 abstract가 dict 형태 {"h1": "Abstract", "p": [" paragraph1 ", ...]}
        # 이므로 p를 공백으로 결합해서 문자열 추출
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
    Elsevier ScienceDirect Search API V2 — WADL: dev.elsevier.com/documentation/ScienceDirectSearchAPI.wadl

    - Endpoint: https://api.elsevier.com/content/search/sciencedirect
      WADL: PUT이 native/recommended, GET은 legacy/emulated이지만 호환을 위해 GET 사용.
      (Scopus Search는 /content/search/scopus — ScienceDirect가 전문(full-text) 클러스터)
    - 인증(AuthenticationAPI.wadl + ScienceDirectSearchAPI.wadl 기준):
        X-ELS-APIKey 헤더 (또는 apiKey 쿼리 override) — 필수
        X-ELS-Insttoken / insttoken — 선택(기관 프록시/원격 접근 시)
        Accept: application/json (또는 httpAccept 쿼리 override) — PUT은 application/json만, GET은 json/atom+xml/xml
    - View: ScienceDirect는 WADL 기준 STANDARD만 허용(default STANDARD). COMPLETE는 Scopus 전용.
      STANDARD엔 초록이 없어 보강: Abstract Retrieval(META, 무료) → Crossref 폴백(DOI).
      단, Article Retrieval(전문)과 Abstract/FULL view는 별도 엔타이틀먼트 필요(401/403).
      (보강 기본 ON / ELSEVIER_SKIP_ABSTRACT_ENRICH=1 로 비활성)
    - Query: Boolean search (예: heart attack AND text(liver)) — WADL query(필수)
      count: 허용값 10,25,50,100 (WADL) — 요청값이 허용 외면 최소 허용값으로 올림
      start: 0-6000 offset, sort: coverDate/relevance 등
    - 제한: 100 Hits/Min (Throttling)
    - API key: .env의 ELSEVIER_API_KEY 또는 인자로 전달 (.env.example 참고)
    - 참고: https://github.com/ElsevierDev/elsapy (archived)
    """
    if api_key is None:
        api_key = os.getenv("ELSEVIER_API_KEY", "")

    if not api_key:
        logger.warning("[Elsevier] API key 없음 - 검색 건너뜀")
        return []

    base_url = "https://api.elsevier.com/content/search/sciencedirect"
    # WADL: count 허용 10,25,50,100 — 5 요청 시 10으로 올림
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

    # Rate limit: 100 Hits/Min = 약 1req/0.6s
    # 1회 요청 후 0.7초 대기 권장
    max_api_retries = 3
    for attempt in range(max_api_retries):
        try:
            r = requests.get(base_url, params=params, headers=headers, timeout=60)
            if r.status_code == 429:
                retry_after = _retry_after_seconds(r.headers)
                logger.warning(f"[Elsevier] Rate limited (429). {retry_after}s 대기 후 재시도 ({attempt+1}/{max_api_retries})...")
                time.sleep(retry_after)
                continue
            if r.status_code == 401:
                logger.warning("[Elsevier] API key 오류 (401) - 무효 (WADL: X-ELS-APIKey/apiKey 확인)")
                return []
            if r.status_code == 403:
                logger.warning("[Elsevier] 권한/구독 오류 (403) - 기관 IP/Insttoken 또는 VIEW 권한 확인 (WADL: X-ELS-Insttoken)")
                return []
            if r.status_code == 500:
                if attempt < max_api_retries - 1:
                    logger.warning(f"[Elsevier] Server Error (500). 재시도 ({attempt+1}/{max_api_retries})...")
                    time.sleep(2 + attempt * 3)
                    continue
            r.raise_for_status()
            data = r.json()
            break
        except requests.exceptions.ConnectionError:
            logger.error(f"[Elsevier] 연결 실패")
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
    # WADL count 정규화로 요청보다 많이 올 수 있으므로 먼저 절단(초록 보강 API 비용도 절감)
    entries = [e for e in entries if isinstance(e, dict)][:max_results]
    skip_enrich = os.getenv("ELSEVIER_SKIP_ABSTRACT_ENRICH", "").strip() in {"1", "true", "yes"}
    for entry in entries:
        # DOI 우선 (multi와 정렬); link는 @href로 안전 파싱 (@URL 키는 응답에 없음, 빈 리스트 IndexError 방지)
        paper_id = entry.get("prism:doi", "") or entry.get("dc:identifier", "") or entry.get("eid", "")
        title = entry.get("dc:title", "")
        url = entry.get("prism:url", "")
        links = entry.get("link") or []
        if isinstance(links, list):
            for l in links:
                if isinstance(l, dict) and l.get("@ref") != "self":
                    href = l.get("@href", "")
                    if href:
                        url = href
                        break
        abstract = entry.get("dc:description", "") or entry.get("dc:abstract", "") or ""
        # STANDARD view엔 초록 필드가 없음 → 보강 순서: Abstract Retrieval(META) → Crossref(DOI)
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

        pub_date = entry.get("prism:coverDate", "") or entry.get("prism:publishedDate", "") or entry.get("dc:date", "") or ""
        # DOI 있으면 사람이 읽는 doi.org 링크로 교체 (multi와 정렬)
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

def search_all(
    topic: str,
    max_results: int = 5,
    lookback_days: int = 1,
) -> List[Paper]:
    """
    모든 출처에서 통합 검색.

    PubMed: lookback_days 필터를 적용 (발표일 기준)
    bioRxiv: lookback_days 필터를 적용 (날짜 범위)
    Semantic Scholar: 최근 것부터 max_results 건 반환 (추가 필터 없음)
    Springer Nature: API key 필요, Open Access 논문 검색
    Elsevier (Scopus/ScienceDirect): API key 필요 (100 Hits/Min)
    """
    all_papers: List[Paper] = []

    # PubMed (발표일 필터)
    pm_papers = search_pubmed(topic, max_results, lookback_days)
    all_papers.extend(pm_papers)

    # bioRxiv (날짜 범위 + 키워드 필터)
    biorxiv_papers = search_biorxiv(topic, max_results, lookback_days)
    all_papers.extend(biorxiv_papers)

    # Semantic Scholar
    ss_papers = search_semantic_scholar(topic, max_results)
    all_papers.extend(ss_papers)

    # Springer Nature Open Access (API key 필요)
    springer_papers = search_springer(topic, max_results)
    all_papers.extend(springer_papers)

    # Elsevier (Scopus/ScienceDirect) - API key 필요
    elsevier_papers = search_elsevier(topic, max_results)
    all_papers.extend(elsevier_papers)

    # 중복 제거 (title 기준, 정규화 후 비교)
    seen: List[str] = []
    unique: List[Paper] = []
    for p in all_papers:
        norm_title = re.sub(r"\s+", "", p.title.lower())
        if norm_title in seen:
            continue
        seen.append(norm_title)
        unique.append(p)

    logger.info(f"[통합] {len(all_papers)}건 → {len(unique)}건 (중복 제거 후)")
    return unique


# ------------------------------------------------------------------
# CLI / 단독 실행
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

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
