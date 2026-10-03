#!/usr/bin/env python3
"""
academic-mcp 직접 호출 클라이언트 — scite_client.py 패턴 재사용
- MCP stdio 프로토콜 우회, searcher 객체 직접 사용 (디버그/운영 공용)
- SKILL.md v1.2.0: "직접 import는 디버그 탐사용으로만 허용" → 이 모듈은 내부 구현체로 격리
- 가상환경 Python으로 실행되는 별도 프로세스(subprocess)로 동작
- JSON-RPC 스타일로 stdin/stdout 통신하여 Hermes 메인 환경(mcp 2.x)과 격리
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# ── 가상환경 Python 경로 탐색 ────────────────────────────────────────

def find_academic_mcp_python() -> Optional[str]:
    """academic-mcp 가상환경의 Python 실행파일 경로 찾기."""
    env_python = os.environ.get("ACADEMIC_MCP_PYTHON")
    if env_python and Path(env_python).exists():
        return env_python

    candidates = [
        Path.home() / "AppData" / "Local" / "Temp" / "academic-mcp-venv" / "Scripts" / "python.exe",
        Path("/tmp/academic-mcp-venv/Scripts/python.exe"),
        Path("/c/Users/user/AppData/Local/Temp/academic-mcp-venv/Scripts/python.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    which_python = shutil.which("python")
    if which_python:
        try:
            result = subprocess.run(
                [which_python, "-c", "import academic_mcp; print('OK')"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return which_python
        except Exception:
            pass
    return None


# ── 워커 스크립트 ───────────────────────────────────────────────────
# academic-mcp 가상환경에서 실행되며 JSON-RPC로 요청 처리.
# datetime 등 비표준 타입은 _PaperEncoder로 직렬화.

WORKER_SCRIPT = r'''
import sys
import os
import json
import datetime as _dt

from academic_mcp.__main__ import ALL_SEARCHERS, SAVE_PATH

# JSON 직렬화 헬퍼: Paper 객체의 datetime 필드 등 비표준 타입 처리
class _PaperEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, _dt.datetime):
            return o.isoformat()
        if isinstance(o, _dt.date):
            return o.isoformat()
        return str(o)

def paper_to_dict(paper) -> dict:
    """Paper 객체를 dict로 변환 (datetime 등 처리 포함)"""
    d = {}
    for k, v in paper.__dict__.items():
        if callable(v):
            continue
        if isinstance(v, (_dt.datetime, _dt.date)):
            d[k] = v.isoformat()
        elif isinstance(v, (str, int, float, bool, type(None))):
            d[k] = v
        elif isinstance(v, (list, tuple)):
            d[k] = [paper_to_dict(item) if hasattr(item, '__dict__') else item for item in v]
        elif isinstance(v, dict):
            d[k] = {kk: (vv.isoformat() if isinstance(vv, (_dt.datetime, _dt.date)) else vv) for kk, vv in v.items()}
        else:
            d[k] = str(v)
    return d


def handle_request(request: dict) -> dict:
    """단일 요청 처리"""
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    try:
        if method == "search":
            query = params.get("query", "")
            max_results = params.get("max_results", 10)
            max_results = params.get("limit", max_results)
            sources = params.get("sources") or ["arxiv", "semantic", "crossref"]
            year_from = params.get("year_from")
            year_to = params.get("year_to")

            all_results = []
            for src in sources:
                if src not in ALL_SEARCHERS:
                    continue
                searcher = ALL_SEARCHERS[src]
                try:
                    results = searcher.search(query, max_results=max_results)
                    for r in results:
                        d = paper_to_dict(r)
                        d["_source"] = src
                        all_results.append(d)
                except Exception as e:
                    pass

            # 연도 필터
            if year_from or year_to:
                filtered = []
                for r in all_results:
                    yr = r.get("year")
                    if yr:
                        try:
                            yr_int = int(yr) if isinstance(yr, str) else yr
                            if yr_int and year_from and yr_int < year_from:
                                continue
                            if yr_int and year_to and yr_int > year_to:
                                continue
                        except (ValueError, TypeError):
                            pass
                    filtered.append(r)
                all_results = filtered

            for r in all_results:
                if "_source" in r:
                    r["source"] = r.pop("_source")

            return {"id": req_id, "result": {"papers": all_results[:max_results]}}

        elif method == "download":
            paper_id = params.get("paper_id")
            source = params.get("source", "arxiv")
            save_path = params.get("save_path") or SAVE_PATH

            if source not in ALL_SEARCHERS:
                return {"id": req_id, "error": f"Unknown source: {source}"}

            searcher = ALL_SEARCHERS[source]
            try:
                pdf_path = searcher.download_pdf(paper_id, save_path)
                if pdf_path and os.path.exists(pdf_path):
                    size = os.path.getsize(pdf_path)
                    return {"id": req_id, "result": {"pdf_path": pdf_path, "size_bytes": size}}
                else:
                    return {"id": req_id, "error": f"Download failed: {pdf_path}"}
            except Exception as e:
                return {"id": req_id, "error": str(e)}

        elif method == "read":
            paper_id = params.get("paper_id")
            source = params.get("source", "arxiv")
            save_path = params.get("save_path") or SAVE_PATH

            if source not in ALL_SEARCHERS:
                return {"id": req_id, "error": f"Unknown source: {source}"}

            searcher = ALL_SEARCHERS[source]
            try:
                text = searcher.read_paper(paper_id, save_path=save_path)
                return {"id": req_id, "result": {"text": text}}
            except Exception as e:
                return {"id": req_id, "error": str(e)}

        elif method == "metadata":
            paper_id = params.get("paper_id")
            source = params.get("source", "arxiv")
            save_path = params.get("save_path") or SAVE_PATH

            if source not in ALL_SEARCHERS:
                return {"id": req_id, "error": f"Unknown source: {source}"}

            searcher = ALL_SEARCHERS[source]
            try:
                text = searcher.read_paper(paper_id, save_path=save_path)
                return {"id": req_id, "result": {
                    "title": getattr(searcher, "last_title", None),
                    "authors": getattr(searcher, "last_authors", None),
                    "year": getattr(searcher, "last_year", None),
                    "doi": getattr(searcher, "last_doi", None),
                    "abstract": (text[:2000] if text else None),
                    "source": source,
                    "paper_id": paper_id,
                }}
            except Exception as e:
                return {"id": req_id, "error": str(e)}

        elif method == "list_sources":
            return {"id": req_id, "result": {"sources": list(ALL_SEARCHERS.keys())}}

        else:
            return {"id": req_id, "error": f"Unknown method: {method}"}

    except Exception as e:
        return {"id": req_id, "error": f"Internal error: {e}"}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            print(json.dumps(response, cls=_PaperEncoder, ensure_ascii=False), flush=True)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON"}), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}, cls=_PaperEncoder, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
'''


# ── AcademicMcpDirect ────────────────────────────────────────────────

class AcademicMcpDirect:
    """
    academic-mcp 직접 호출 클라이언트 (async context manager)

    내부적으로 가상환경 Python subprocess를 띄워 JSON-RPC로 통신.
    Hermes 메인 환경(mcp 2.x)과 academic-mcp 환경(mcp 1.x) 완전 격리.

    사용 예:
        async with AcademicMcpDirect() as client:
            papers = await client.search("attention is all you need", limit=5)
            pdf_path = await client.download("2106.03801", source="arxiv")
            text = await client.read("2106.03801", source="arxiv")
    """

    def __init__(
        self,
        python_path: str | None = None,
        download_dir: str | None = None,
        enabled_sources: list[str] | None = None,
    ):
        self.python_path = python_path or find_academic_mcp_python()
        if not self.python_path:
            raise RuntimeError(
                "academic-mcp 가상환경 Python을 찾을 수 없습니다. "
                "ACADEMIC_MCP_PYTHON 환경변수를 설정하거나 가상환경을 생성하세요."
            )

        self.download_dir = download_dir or str(
            Path.home() / "AppData" / "Local" / "Temp" / "academic-papers"
        )
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)

        self.enabled_sources = enabled_sources or [
            "arxiv", "pubmed", "pmc", "biorxiv", "medrxiv",
            "semantic", "crossref", "google_scholar", "iacr", "core"
        ]

        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0

        print(f"🔧 AcademicMcpDirect 초기화:")
        print(f"   Python: {self.python_path}")
        print(f"   다운로드: {self.download_dir}")
        print(f"   활성 소스: {', '.join(self.enabled_sources)}")

    async def __aenter__(self):
        print(f"🔌 academic-mcp 워커 프로세스 시작 중...")

        env = {
            **os.environ,
            "ACADEMIC_MCP_DOWNLOAD_PATH": self.download_dir,
            "ACADEMIC_MCP_ENABLED_SOURCES": ",".join(self.enabled_sources),
            "ACADEMIC_MCP_DISABLED_SOURCES": "ieee,scopus,springer,sciencedirect,wos,acm,jstor,researchgate",
        }

        self._process = subprocess.Popen(
            [self.python_path, "-c", WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )

        # Request lock for concurrency safety
        self._request_lock = asyncio.Lock()

        try:
            sources = await asyncio.wait_for(self.list_sources(), timeout=15.0)
            print(f"✅ academic-mcp 워커 연결 완료 (활성 소스: {len(sources)}개)")
            return self
        except asyncio.TimeoutError:
            # Cleanup process properly
            if self._process:
                self._process.terminate()
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._process.wait), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    self._process.kill()
                    await asyncio.to_thread(self._process.wait)
            raise RuntimeError("워커 프로세스 시작 타임아웃 (15s)")

    async def __aexit__(self, *args):
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._process.wait), timeout=5.0
                )
            except asyncio.TimeoutError:
                self._process.kill()
                await asyncio.to_thread(self._process.wait)
        print(f"🔌 academic-mcp 워커 프로세스 종료")

    # ── 내부 통신 ──────────────────────────────────────────────────

    async def _call(self, method: str, **params) -> dict | None:
        if not self._process or self._process.poll() is not None:
            raise RuntimeError("워커 프로세스가 실행 중이 아닙니다.")

        self._request_id += 1
        req_id = self._request_id
        request = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}

        loop = asyncio.get_running_loop()

        async with self._request_lock:
            def _write_request():
                print(json.dumps(request), file=self._process.stdin, flush=True)

            await loop.run_in_executor(None, _write_request)

            try:
                line = await asyncio.wait_for(
                    loop.run_in_executor(None, self._process.stdout.readline),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                # Don't terminate immediately - may be slow response
                raise RuntimeError("워커 프로세스 응답 타임아웃 (60s)")

            if not line:
                # Process may have exited
                if self._process.poll() is not None:
                    stderr = self._process.stderr.read() if self._process.stderr else ""
                    raise RuntimeError(f"워커 프로세스 종료됨: {stderr}")
                raise RuntimeError("워커 프로세스 응답 없음 (EOF)")

            try:
                response = json.loads(line.strip())
            except json.JSONDecodeError as e:
                raise RuntimeError(f"워커 응답 파싱 실패: {line}") from e

            # Validate response ID matches request
            if response.get("id") != req_id:
                raise RuntimeError(f"응답 ID 불일치: 예상 {req_id}, 수신 {response.get('id')}")

            if "error" in response:
                raise RuntimeError(f"워커 오류: {response['error']}")

            return response.get("result")

    # ── 공개 메서드 ────────────────────────────────────────────────

    async def list_sources(self) -> list[str]:
        """사용 가능한 소스 목록 조회"""
        result = await self._call("list_sources")
        return result.get("sources", []) if result else []

    async def search(
        self,
        query: str,
        limit: int = 10,
        sources: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[dict]:
        """
        논문 검색.

        Args:
            query: 검색어
            limit: 최대 결과 수 (alias: max_results)
            sources: 검색할 소스 목록 (None이면 모든 활성 소스)
            year_from: 시작 연도
            year_to: 종료 연도

        Returns:
            논문 리스트 (title, authors, year, doi, source, source_url 등 포함)
        """
        result = await self._call(
            "search",
            query=query,
            max_results=limit,
            limit=limit,
            sources=sources or self.enabled_sources,
            year_from=year_from,
            year_to=year_to,
        )
        return result.get("papers", []) if result else []

    async def download(
        self,
        paper_id: str,
        source: str = "arxiv",
        save_path: str | None = None,
    ) -> str | None:
        """
        논문 PDF 다운로드.

        Args:
            paper_id: 논문 식별자 (arXiv ID, PMID, DOI 등)
            source: 소스명
            save_path: 저장 경로 (기본값: download_dir)

        Returns:
            PDF 파일 경로 또는 None
        """
        result = await self._call(
            "download",
            paper_id=paper_id,
            source=source,
            save_path=save_path or self.download_dir,
        )
        if result:
            return result.get("pdf_path")
        return None

    async def read(
        self,
        paper_id: str,
        source: str = "arxiv",
        save_path: str | None = None,
    ) -> str | None:
        """
        논문 본문 텍스트 읽기.

        Args:
            paper_id: 논문 식별자
            source: 소스명
            save_path: 저장 경로 (기본값: download_dir)

        Returns:
            추출된 텍스트 또는 None
        """
        result = await self._call("read", paper_id=paper_id, source=source, save_path=save_path or self.download_dir)
        if result:
            return result.get("text")
        return None

    async def metadata(
        self,
        paper_id: str,
        source: str = "arxiv",
    ) -> dict | None:
        """논문 메타데이터 조회."""
        result = await self._call("metadata", paper_id=paper_id, source=source)
        return result


# ── 스탠드얼론 테스트 ────────────────────────────────────────────────

async def _standalone_test():
    print("=" * 60)
    print("  AcademicMcpDirect 스탠드얼론 테스트")
    print("=" * 60)

    try:
        async with AcademicMcpDirect() as client:
            # 1. 소스 목록
            print("\n📋 소스 목록:")
            sources = await client.list_sources()
            for s in sources:
                print(f"   - {s}")

            # 2. 검색 테스트
            print("\n🔍 search 테스트: 'attention is all you need'")
            papers = await client.search("attention is all you need", limit=3, sources=["arxiv"])
            print(f"   결과: {len(papers)}개")
            for p in papers[:2]:
                print(f"   - {p.get('title', '?')[:60]} ({p.get('source', '?')})")

            # 3. 다운로드 테스트 (arXiv)
            print("\n📥 download 테스트: arXiv 2106.03801")
            pdf_path = await client.download("2106.03801", source="arxiv")
            if pdf_path and Path(pdf_path).exists():
                size = Path(pdf_path).stat().st_size
                print(f"   ✅ {pdf_path} ({size:,} bytes)")
            else:
                print(f"   ❌ 다운로드 실패: {pdf_path}")

            # 4. 읽기 테스트
            print("\n📖 read 테스트: arXiv 2106.03801")
            text = await client.read("2106.03801", source="arxiv")
            if text:
                print(f"   ✅ 텍스트 길이: {len(text):,}자")
                print(f"   앞 300자: {text[:300]}...")
            else:
                print("   ❌ 읽기 실패")

            # 5. 메타데이터 테스트
            print("\n📄 metadata 테스트: arXiv 2106.03801")
            meta = await client.metadata("2106.03801", source="arxiv")
            if meta:
                print(f"   제목: {meta.get('title')}")
                print(f"   저자: {meta.get('authors')}")
                print(f"   연도: {meta.get('year')}")

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(_standalone_test())