"""
scite MCP 클라이언트 — 재사용 가능한 핵심 함수 모음

사용 예:
    from scite_client import SciteClient, parse_mcp_result
    async with SciteClient() as scite:
        paper = await scite.search_by_doi("10.18653/v1/N19-1423")
        graph = await scite.citation_graph([paper["doi"]], direction="in")
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ── 토큰 로딩 ────────────────────────────────────────────────────────

def load_token() -> str | None:
    """~/.hermes/.env에서 SCITE_ACCESS_TOKEN 읽기 (UTF-16 등 대응)"""
    token = os.environ.get("SCITE_ACCESS_TOKEN")
    if token:
        return token
    env_file = Path.home() / ".hermes" / ".env"
    if not env_file.exists():
        return None
    raw = None
    for enc in ("utf-8-sig", "utf-8", "utf-16-le", "cp949"):
        try:
            raw = env_file.read_text(encoding=enc)
            break
        except Exception:
            continue
    if raw:
        for line in raw.splitlines():
            if line.startswith("SCITE_ACCESS_TOKEN="):
                token = line.split("=", 1)[1].strip()
                if token:
                    return token
    return None


# ── 결과 파싱 ────────────────────────────────────────────────────────

def parse_mcp_result(result_raw: Any) -> dict | None:
    """
    CallToolResult 객체 → 내부 JSON 문자열 추출 → 파싱된 dict.
    실패 시 None.
    """
    try:
        outer = json.loads(result_raw.model_dump_json())
        blocks = outer.get("content", [])
        if not blocks or not isinstance(blocks, list):
            return None
        text = blocks[0].get("text", "")
        if not text:
            return None
        return json.loads(text)
    except Exception:
        return None


# ── SciteClient ──────────────────────────────────────────────────────

class SciteClient:
    """scite MCP 서버에 연결된 클라이언트 (async context manager)"""

    BASE_URL = "https://api.scite.ai/mcp"

    def __init__(self, token: str | None = None):
        self.token = token or load_token()
        if not self.token:
            raise ValueError("SCITE_ACCESS_TOKEN이 없습니다. OAuth 인증을 먼저 실행하세요.")
        self._client = None
        self._stream_cm = None  # streamable_http_client context manager
        self._streams = None
        self._session = None

    async def __aenter__(self):
        import httpx
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=60.0,
        )
        self._stream_cm = streamable_http_client(self.BASE_URL, http_client=self._client)
        self._streams = await self._stream_cm.__aenter__()
        read, write = self._streams
        self._session = await ClientSession(read, write).__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.__aexit__(*args)
        if self._stream_cm:
            await self._stream_cm.__aexit__(*args)
        if self._client:
            await self._client.__aexit__(*args)

    # ── 도구 호출 헬퍼 ──

    async def _call(self, tool_name: str, **kwargs) -> dict | None:
        result = await self._session.call_tool(tool_name, arguments=kwargs)
        return parse_mcp_result(result)

    # ── 공개 도구 ──

    async def paper_by_doi(self, doi: str) -> dict | None:
        """DOI로 논문 1건의 메타데이터 + Smart Citations 조회"""
        data = await self._call("search_literature", dois=[doi], limit=1)
        if data and data.get("hits"):
            return data["hits"][0]
        return None

    async def paper_by_title(self, title: str) -> dict | None:
        """제목으로 논문 1건 조회"""
        data = await self._call("search_literature", titles=[title], limit=1)
        if data and data.get("hits"):
            return data["hits"][0]
        return None

    async def search(self, term: str, limit: int = 10, **filters) -> list[dict]:
        """키워드 검색 + 필터. 반환: hits 리스트"""
        data = await self._call("search_literature", term=term, limit=limit, **filters)
        return data.get("hits", []) if data else []

    async def citation_graph(self, doi: str, limit: int = 50,
                            direction: str = "in", depth: int = 1,
                            include_intent: bool = True) -> dict:
        """
        인용 그래프 조회.
        반환: {"edges": [...], "papers": {...}, "truncated": bool, "seed_coverage": {...}}
        """
        return await self._call("citation_graph", seeds=[doi], direction=direction,
                                 depth=depth, max_edges=limit, include_intent=include_intent)

    async def editorial_notices(self, doi: str) -> dict:
        """
        편집자 공지 사항 조회 (retraction, corrected, concern 등).
        반환: {notices: [{"type": "retracted", "title": "...", "url": "..."}]}
        """
        return await self._call("editorialNotices", doi=doi)

    async def read_fulltext(self, doi: str, offset: int = 0, length: int = 8000) -> dict:
        """논문 본문 일부 읽기 (페이지 단위)"""
        return await self._call("read_fulltext", doi=doi, offset=offset, length=length)

    async def bibliography(self, dois: list[str], fmt: str = "bibtex") -> dict:
        """DOI 목록 → BibTeX/RIS/CSV"""
        return await self._call("bibliography", dois=dois, format=fmt)

    async def tally(self, doi: str) -> dict | None:
        """논문 Smart Citation 집계만 빠르게 조회"""
        paper = await self.paper_by_doi(doi)
        return paper.get("tally", {}) if paper else None


# ── 스탠드얼론 실행: 빠른 테스트 ────────────────────────────────────

async def _standalone_test():
    async with SciteClient() as scite:
        # BERT 논문
        bert = await scite.paper_by_doi("10.18653/v1/N19-1423")
        if bert:
            print(f"📄 {bert['title']}")
            print(f"   총 인용: {bert.get('tally',{}).get('total',0)}")
            print(f"   지원/언급/반박: "
                  f"{bert.get('tally',{}).get('supporting',0)}/"
                  f"{bert.get('tally',{}).get('mentioning',0)}/"
                  f"{bert.get('tally',{}).get('contrasting',0)}")
        else:
            print("❌ BERT 논문을 찾을 수 없음")

        # 인용 그래프
        graph = await scite.citation_graph("10.18653/v1/N19-1423", limit=10)
        if graph:
            print(f"\n🔗 인용 논문: {len(graph.get('papers',{}))}개, "
                  f"엣지: {len(graph.get('edges',[]))}개")


if __name__ == "__main__":
    asyncio.run(_standalone_test())
