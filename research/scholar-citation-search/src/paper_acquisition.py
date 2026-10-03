#!/usr/bin/env python3
"""
논문 본문 확보 — 3-tier 통합 (SKILL.md v1.2.0)

Tier1: OA 직접 다운로드 (open_access_url/arxiv_pdf_url 등 → httpx 바이너리 GET → 저장)
Tier2: web_extract로 랜딩 페이지 재탐색 → PDF 링크 발견 시 Tier1 방식으로 다운로드
Tier3: academic-mcp paper_download (AcademicMcpDirect)
Fallback: abstract_only (acquisition_method="abstract_only", pdf_path=None)

출력: {pdf_path, pdf_sha256, acquisition_method}
"""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Optional

import httpx

from academic_mcp_direct import AcademicMcpDirect

# ── Tier1: OA PDF 직접 다운로드 ──────────────────────────────────────

async def fetch_pdf_direct(
    pdf_url: str,
    save_dir: Path,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = 60.0,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_size: int = 100 * 1024 * 1024,  # 100MB 기본 제한
) -> tuple[Optional[Path], Optional[str], Optional[str]]:
    """
    PDF URL에서 직접 다운로드 (Tier1). 지수 백오프 3회 재시도.
    호출자 소유 client는 닫지 않음 (내부에서 별도 client 사용).

    Returns:
        (pdf_path, sha256, error_message)
        성공 시 error_message=None
    """
    last_err = None
    for attempt in range(max_retries):
        # 호출자 client를 닫지 않기 위해 항상 내부 client 사용
        # (재시도 시 닫힌 client 재사용 방지)
        own_client = client is None
        c = client if not own_client else httpx.AsyncClient()
        try:
            resp = await c.get(pdf_url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            if "pdf" not in content_type and "application/octet-stream" not in content_type:
                pass

            # 스트리밍으로 크기 제한 적용
            pdf_bytes = b""
            async for chunk in resp.aiter_bytes():
                pdf_bytes += chunk
                if len(pdf_bytes) > max_size:
                    return None, None, f"파일 크기 초과 ({max_size} bytes)"

            if not pdf_bytes:
                return None, None, "빈 응답"

            if not pdf_bytes.startswith(b"%PDF"):
                return None, None, f"PDF 매직 바이트 없음 (처음 20바이트: {pdf_bytes[:20]!r})"

            # 안전한 파일명 결정
            from urllib.parse import urlparse, unquote
            parsed = urlparse(pdf_url)
            url_path = unquote(parsed.path).rstrip("/").split("/")[-1]
            if not url_path or "." not in url_path:
                url_path = "paper.pdf"
            # Windows 파일명 정제
            url_path = re.sub(r'[\\/:*?"<>|]', "_", url_path)
            save_path = save_dir / url_path

            if save_path.exists():
                existing_hash = hashlib.sha256(save_path.read_bytes()).hexdigest()
                new_hash = hashlib.sha256(pdf_bytes).hexdigest()
                if existing_hash == new_hash:
                    return save_path, new_hash, None
                else:
                    stem = save_path.stem
                    suffix = save_path.suffix
                    counter = 2
                    while (save_dir / f"{stem}_{counter}{suffix}").exists():
                        counter += 1
                    save_path = save_dir / f"{stem}_{counter}{suffix}"

            # 원자적 저장
            tmp_path = save_path.with_suffix(".tmp")
            tmp_path.write_bytes(pdf_bytes)
            tmp_path.replace(save_path)
            sha256 = hashlib.sha256(pdf_bytes).hexdigest()

            return save_path, sha256, None

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            last_err = e
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
        except Exception as e:
            return None, None, f"다운로드 오류: {e}"
        finally:
            if own_client:
                await c.aclose()

    return None, None, f"재시도 {max_retries}회 실패: {last_err}"


# ── Tier2: web_extract로 PDF 링크 재탐색 ────────────────────────────

async def find_pdf_link_via_web_extract(
    landing_url: str,
    timeout: float = 30.0,
) -> Optional[str]:
    """
    웹 랜딩 페이지에서 PDF 링크를 재탐색 (Tier2).

    Args:
        landing_url: 논문 랜딩 페이지 URL (DOI 리졸버 등)

    Returns:
        발견된 PDF URL 또는 None
    """
    try:
        from hermes_tools import web_extract

        result = web_extract(urls=[landing_url], char_limit=50000)
        if result.get("error"):
            return None

        content = result.get("content", "")
        if not content:
            # result["results"] 확인
            results = result.get("results", [])
            if results:
                content = results[0].get("content", "") or ""

        if not content:
            return None

        # PDF 링크 패턴 탐색
        import re

        # 1. 직접 PDF URL 패턴
        pdf_patterns = [
            r'https?://[^\s"\']+\.pdf[^\s"\']*',
            r'href=["\'](https?://[^\s"\']*\.pdf[^\s"\']*)["\']',
            r'["\'](https?://[^\s"\']*\.pdf[^\s"\']*)["\']',
            r'/pdf/[^\s"\']+',
        ]

        candidates = []
        for pattern in pdf_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                url = match.group(1) if match.lastindex else match.group(0)
                if url and "pdf" in url.lower():
                    candidates.append(url)

        if candidates:
            # 가장 짧은(상대적 경오일 가능성 낮은) 후보를 우선
            # 절대 URL 우선, .pdf 포함 우선
            for c in sorted(candidates, key=lambda x: (not x.startswith("http"), len(x))):
                if c.startswith("http"):
                    return c
                elif c.startswith("//"):
                    return f"https:{c}"
                else:
                    # 상대 경로를 landing_url 기준으로 해결
                    from urllib.parse import urljoin
                    return urljoin(landing_url, c)

        return None

    except Exception as e:
        return None


# ── Tier3: academic-mcp download ─────────────────────────────────────

async def download_via_academic_mcp(
    paper_id: str,
    source: str,
    save_dir: Path,
    python_path: Optional[str] = None,
    enabled_sources: Optional[list[str]] = None,
) -> tuple[Optional[Path], Optional[str], Optional[str]]:
    """
    academic-mcp paper_download로 PDF 확보 (Tier3).

    Returns:
        (pdf_path, sha256, error_message)
    """
    try:
        async with AcademicMcpDirect(
            python_path=python_path,
            download_dir=str(save_dir),
            enabled_sources=enabled_sources,
        ) as client:
            pdf_path = await client.download(paper_id, source=source)
            if pdf_path and Path(pdf_path).exists():
                sha256 = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
                return Path(pdf_path), sha256, None
            else:
                return None, None, f"academic-mcp 다운로드 실패: {pdf_path}"

    except Exception as e:
        return None, None, f"academic-mcp 오류: {e}"


# ── 통합: 3-tier 본문 확보 ──────────────────────────────────────────

async def acquire_paper_body(
    paper: dict,
    save_dir: Path,
    paper_id: Optional[str] = None,
    source: Optional[str] = None,
    landing_url: Optional[str] = None,
    open_access_url: Optional[str] = None,
    arxiv_pdf_url: Optional[str] = None,
    python_path: Optional[str] = None,
    enabled_sources: Optional[list[str]] = None,
    timeout: float = 60.0,
) -> dict:
    """
    3-tier fallback로 논문 본문 PDF 확보.

    Args:
        paper: 논문 메타딕셔너리 (search 결과로 얻은 것)
        save_dir: PDF 저장 디렉토리
        paper_id: academic-mcp용 식별자 (예: arXiv ID)
        source: academic-mcp 소스명
        landing_url: DOI 리졸버 URL 등 (Tier2에서 사용)
        open_access_url: OA PDF URL (Tier1)
        arxiv_pdf_url: arXiv PDF URL (Tier1)
        python_path: academic-mcp 가상환경 Python 경로
        enabled_sources: academic-mcp 활성 소스 목록
        timeout: HTTP 요청 타임아웃

    Returns:
        {
            "pdf_path": Path | None,
            "pdf_sha256": str | None,
            "acquisition_method": "oa_direct" | "web_fetch" | "academic_mcp" | "abstract_only",
            "tier_attempted": int,
            "tier_result": str,  # 각 tier 처리 결과 요약
            "error": str | None,
        }
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    tier_attempted = 0
    tier_results = []
    error = None
    pdf_path = None
    pdf_sha256 = None
    acquisition_method = "abstract_only"

    # ── Tier1: OA 직접 다운로드 ─────────────────────────────────
    tier_attempted = 1
    tier1_urls = []

    if open_access_url:
        tier1_urls.append(("open_access_url", open_access_url))
    if arxiv_pdf_url:
        tier1_urls.append(("arxiv_pdf_url", arxiv_pdf_url))

    # search 결과에서 source_url이 PDF URL이면 사용
    source_url = paper.get("source_url") or paper.get("url") or paper.get("link")
    if source_url and (source_url.endswith(".pdf") or "arxiv.org/pdf" in source_url):
        # 이미 arxiv_pdf_url로 처리되지 않았다면 추가
        if not arxiv_pdf_url or source_url != arxiv_pdf_url:
            tier1_urls.append(("source_url", source_url))

    for label, url in tier1_urls:
        tier_results.append(f"Tier1 ({label}): 시도 중...")
        path, sha, err = await fetch_pdf_direct(url, save_dir, timeout=timeout)
        if path:
            tier_results.append(f"Tier1 ({label}): 성공 → {path.name} ({sha[:12]}...)")
            pdf_path = path
            pdf_sha256 = sha
            acquisition_method = "oa_direct"
            break
        else:
            tier_results.append(f"Tier1 ({label}): 실패 — {err}")

    if pdf_path:
        return {
            "pdf_path": pdf_path,
            "pdf_sha256": pdf_sha256,
            "acquisition_method": acquisition_method,
            "tier_attempted": tier_attempted,
            "tier_result": " | ".join(tier_results),
            "error": None,
        }

    # ── Tier2: web_extract 랜딩 재탐색 ───────────────────────────
    tier_attempted = 2
    if landing_url:
        tier_results.append("Tier2: landing page 재탐색 시도...")
        pdf_url = await find_pdf_link_via_web_extract(landing_url, timeout=timeout)
        if pdf_url:
            tier_results.append(f"Tier2: PDF 링크 발견 → {pdf_url}")
            path, sha, err = await fetch_pdf_direct(pdf_url, save_dir, timeout=timeout)
            if path:
                tier_results.append(f"Tier2: 다운로드 성공 → {path.name} ({sha[:12]}...)")
                pdf_path = path
                pdf_sha256 = sha
                acquisition_method = "web_fetch"
            else:
                tier_results.append(f"Tier2: 다운로드 실패 — {err}")
        else:
            tier_results.append("Tier2: PDF 링크 발견 실패")

    if pdf_path:
        return {
            "pdf_path": pdf_path,
            "pdf_sha256": pdf_sha256,
            "acquisition_method": acquisition_method,
            "tier_attempted": tier_attempted,
            "tier_result": " | ".join(tier_results),
            "error": None,
        }

    # ── Tier3: academic-mcp ──────────────────────────────────────
    tier_attempted = 3
    tier_results.append("Tier3: academic-mcp paper_download 시도...")

    if paper_id:
        path, sha, err = await download_via_academic_mcp(
            paper_id=paper_id,
            source=source or "arxiv",
            save_dir=save_dir,
            python_path=python_path,
            enabled_sources=enabled_sources,
        )
        if path:
            tier_results.append(f"Tier3: 성공 → {path.name} ({sha[:12]}...)")
            pdf_path = path
            pdf_sha256 = sha
            acquisition_method = "academic_mcp"
        else:
            tier_results.append(f"Tier3: 실패 — {err}")
    else:
        tier_results.append("Tier3: paper_id 없어 건너뛰었습니다")

    if pdf_path:
        return {
            "pdf_path": pdf_path,
            "pdf_sha256": pdf_sha256,
            "acquisition_method": acquisition_method,
            "tier_attempted": tier_attempted,
            "tier_result": " | ".join(tier_results),
            "error": None,
        }

    # ── Fallback: abstract_only ───────────────────────────────────
    tier_results.append("Fallback: abstract_only로 강등")
    acquisition_method = "abstract_only"

    return {
        "pdf_path": None,
        "pdf_sha256": None,
        "acquisition_method": acquisition_method,
        "tier_attempted": tier_attempted,
        "tier_result": " | ".join(tier_results),
        "error": "모든 tier에서 PDF 다운로드 실패",
    }


# ── 스탠드얼론 테스트 ────────────────────────────────────────────────

async def _standalone_test():
    from pathlib import Path

    save_dir = Path.home() / "AppData" / "Local" / "Temp" / "test-papers"
    save_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  3-tier 본문 확보 통합 테스트")
    print("=" * 60)

    # 테스트 논문 (search 결과 스타일)
    test_paper = {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "..."],
        "year": 2017,
        "source": "arxiv",
        "source_url": "https://arxiv.org/pdf/1706.03762.pdf",
        "arxiv_id": "1706.03762",
    }

    print(f"\n📄 테스트 논문: {test_paper['title']}")
    print(f"   소스: {test_paper['source']}")
    print(f"   arXiv ID: {test_paper['arxiv_id']}")

    result = await acquire_paper_body(
        paper=test_paper,
        save_dir=save_dir,
        paper_id=test_paper["arxiv_id"],
        source="arxiv",
        open_access_url=test_paper["source_url"],
        arxiv_pdf_url=test_paper["source_url"],
    )

    print(f"\n📊 결과:")
    print(f"   acquisition_method: {result['acquisition_method']}")
    print(f"   tier_attempted: {result['tier_attempted']}")
    print(f"   pdf_path: {result['pdf_path']}")
    print(f"   pdf_sha256: {result['pdf_sha256']}")
    print(f"   error: {result['error']}")
    print(f"\n   tier_result:")
    for line in result['tier_result'].split(" | "):
        print(f"     {line}")

    # 결과 JSON 저장
    result_file = save_dir / "acquisition_result.json"
    serializable = {
        k: (str(v) if isinstance(v, Path) else v)
        for k, v in result.items()
    }
    result_file.write_text(json.dumps(serializable, indent=2, ensure_ascii=False))
    print(f"\n✅ 결과 저장: {result_file}")


if __name__ == "__main__":
    asyncio.run(_standalone_test())