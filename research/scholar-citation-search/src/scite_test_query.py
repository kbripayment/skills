#!/usr/bin/env python3
"""
scite MCP: 실제 논문 조회 테스트
- search_literature로 DOI 기반 논문 메타데이터 + Smart Citations 조회
- citation_graph로 인용 관계 탐색
"""

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def load_token():
    token = os.environ.get("SCITE_ACCESS_TOKEN")
    if token:
        return token
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
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


def parse_mcp_result(result_raw) -> dict | None:
    """CallToolResult → 내부 JSON 파싱 → dict 반환. 실패하면 None."""
    try:
        parsed = json.loads(result_raw.model_dump_json())
        blocks = parsed.get("content", [])
        if not blocks or not isinstance(blocks, list):
            return None
        text = blocks[0].get("text", "")
        if not text:
            return None
        return json.loads(text)
    except Exception:
        return None


async def main():
    token = load_token()
    if not token:
        print("❌ SCITE_ACCESS_TOKEN을 찾을 수 없습니다.")
        return

    print(f"✅ 토큰 로드 완료 (길이: {len(token)})")
    url = "https://api.scite.ai/mcp"

    import httpx
    client = httpx.AsyncClient(
        base_url=url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    )

    async with streamable_http_client(url, http_client=client) as streams:
        read, write = streams
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ── 테스트 1: search_literature (DOI 기반) ──
            print("\n" + "=" * 60)
            print("  테스트 1: search_literature (DOI 기반 메타데이터)")
            print("=" * 60)

            test_dois = [
                ("10.5555/3295223.3295349", "Attention Is All You Need"),
                ("10.18653/v1/N19-1423", "BERT"),
            ]

            for doi, label in test_dois:
                print(f"\n📄 [{label}] DOI: {doi}")
                try:
                    result_raw = await session.call_tool("search_literature", {
                        "dois": [doi], "limit": 1,
                    })
                    content = parse_mcp_result(result_raw)
                    if content is None:
                        print("  ⚠️ 응답 파싱 실패")
                        continue
                    hits = content.get("hits", [])
                    if not hits:
                        print("  ⚠️ 결과 없음")
                        continue
                    h = hits[0]
                    print(f"  제목: {h.get('title', '?')}")
                    print(f"  저자: {', '.join(a.get('authorName','') for a in h.get('authors',[]))}")
                    print(f"  연도: {h.get('year')}, 저널: {h.get('journal')}")
                    tally = h.get("tally", {})
                    print(f"  📊 Smart Citations: 총{tally.get('total',0)} "
                          f"(S:{tally.get('supporting',0)} M:{tally.get('mentioning',0)} "
                          f"C:{tally.get('contrasting',0)})")
                    print(f"     인용 논문 수: {tally.get('citing_publications', 0)}")
                    if h.get("citations"):
                        print(f"  📋 스마트 인용 예시 (최대 3개):")
                        for c in h["citations"][:3]:
                            print(f"     [{c.get('type','?')}] {c.get('snippet','')[:120]}")
                            print(f"       섹션: {c.get('section','?')}, 출처DOI: {c.get('sourceDoi','?')}")
                    else:
                        print(f"  📋 스마트 인용: 없음")
                    if h.get("editorialNotices"):
                        print(f"  ⚠️ 편집 공지: {h['editorialNotices']}")
                    acc = h.get("access", {})
                    print(f"  접근: {acc.get('url','?')} ({acc.get('accessType','?')})")
                except Exception as e:
                    print(f"  ❌ 오류: {e}")

            # ── 테스트 2: citation_graph ──
            print("\n" + "=" * 60)
            print("  테스트 2: citation_graph (인용 관계)")
            print("=" * 60)

            seed_doi = "10.18653/v1/N19-1423"  # BERT
            print(f"\n🌱 Seed DOI: {seed_doi}")
            print("  → direction='in' (이 논문을 인용한 논문들)")

            try:
                result_raw = await session.call_tool("citation_graph", {
                    "seeds": [seed_doi],
                    "direction": "in",
                    "depth": 1,
                    "max_edges": 20,
                    "include_intent": True,
                })
                content = parse_mcp_result(result_raw)
                if content is None:
                    print("  ⚠️ 응답 파싱 실패")
                else:
                    edges = content.get("edges", [])
                    papers = content.get("papers", {})
                    truncated = content.get("truncated", False)
                    seed_cov = content.get("seed_coverage", {})
                    print(f"  📊 결과: {len(edges)}개 엣지, truncated={truncated}")
                    print(f"  📊 seed_coverage: {seed_cov}")
                    if papers:
                        print(f"\n  📌 인용 논문 (최대 10개):")
                        for i, (dk, pinfo) in enumerate(papers.items()):
                            if i >= 10:
                                break
                            print(f"    [{i+1}] {pinfo.get('title','?')[:80]}")
                            print(f"        DOI: {dk}, 연도: {pinfo.get('year','?')}")
                    if edges:
                        print(f"\n  🔗 인용 엣지 예시 (최대 5개, intent 포함):")
                        for edge in edges[:5]:
                            s = edge.get("s", "?")
                            t = edge.get("t", "?")
                            d = edge.get("d", "?")
                            intent = edge.get("intent", {})
                            print(f"    {str(s)[:30]}... → {str(t)[:30]}... (hop={d})")
                            if intent:
                                print(f"      type: {intent.get('type','?')}, section: {intent.get('section','?')}")
                                if intent.get("snippets"):
                                    print(f"      snippet: {intent['snippets'][0][:100]}")
            except Exception as e:
                print(f"  ❌ 오류: {e}")

            # ── 테스트 3: 키워드 검색 ──
            print("\n" + "=" * 60)
            print("  테스트 3: search_literature (키워드 검색)")
            print("=" * 60)

            print("\n🔍 검색: 'transformer attention mechanism' (limit=3)")
            try:
                result_raw = await session.call_tool("search_literature", {
                    "term": "transformer attention mechanism",
                    "limit": 3,
                })
                content = parse_mcp_result(result_raw)
                if content is None:
                    print("  ⚠️ 응답 파싱 실패")
                else:
                    hits = content.get("hits", [])
                    print(f"  📊 {len(hits)}개 결과:")
                    for h in hits:
                        tally = h.get("tally", {})
                        print(f"\n  📄 {h.get('title','?')[:80]}")
                        print(f"     DOI: {h.get('doi')}")
                        print(f"     저자: {', '.join(a.get('authorName','') for a in h.get('authors',[]))[:60]}")
                        print(f"     연도: {h.get('year')}, 저널: {h.get('journal')}")
                        print(f"     📊 인용: 총{tally.get('total',0)} "
                              f"(S:{tally.get('supporting',0)} M:{tally.get('mentioning',0)} "
                              f"C:{tally.get('contrasting',0)})")
                        if h.get("abstract"):
                            print(f"     초록: {h['abstract'][:150]}...")
            except Exception as e:
                print(f"  ❌ 오류: {e}")

    print("\n" + "=" * 60)
    print("  ✅ 테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
