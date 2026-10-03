#!/usr/bin/env python3
"""scite MCP 호출 결과 구조 디버깅"""

import asyncio
import os
import json
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


async def main():
    token = load_token()
    if not token:
        print("❌ 토큰 없음")
        return

    import httpx
    client = httpx.AsyncClient(
        base_url="https://api.scite.ai/mcp",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    )

    async with streamable_http_client("https://api.scite.ai/mcp", http_client=client) as streams:
        read, write = streams
        async with ClientSession(read, write) as session:
            await session.initialize()

            # search_literature 호출
            result = await session.call_tool("search_literature", {
                "dois": ["10.18653/v1/N19-1423"],
                "limit": 1,
            })

            print("=== result 타입 ===")
            print(type(result))
            print(f"dir(result): {[x for x in dir(result) if not x.startswith('_')]}")

            # content 필드 확인
            if hasattr(result, "content"):
                print(f"\n=== result.content 타입: {type(result.content)} ===")
                print(f"len: {len(result.content)}")
                for i, block in enumerate(result.content[:3]):
                    print(f"\n--- block[{i}] 타입: {type(block)} ---")
                    print(f"  dir: {[x for x in dir(block) if not x.startswith('_')]}")
                    if hasattr(block, "text"):
                        print(f"  text (앞 300자): {block.text[:300]}")
                    elif isinstance(block, dict):
                        print(f"  dict keys: {list(block.keys())}")
                        for k, v in list(block.items())[:5]:
                            print(f"  {k}: {str(v)[:200]}")

            # 모델_dump 시도 (pydantic)
            if hasattr(result, "model_dump"):
                print("\n=== model_dump() ===")
                dumped = result.model_dump()
                print(f"type: {type(dumped)}")
                if isinstance(dumped, dict):
                    for k, v in dumped.items():
                        print(f"  {k}: {type(v)} = {str(v)[:200]}")
                elif isinstance(dumped, list):
                    print(f"  list, len={len(dumped)}")
                    for item in dumped[:2]:
                        print(f"  item: {type(item)} = {str(item)[:200]}")

            # model_dump_json 시도
            if hasattr(result, "model_dump_json"):
                print("\n=== model_dump_json() ===")
                j = result.model_dump_json()
                print(f"type: {type(j)}")
                print(f"앞 500자: {j[:500]}")
                parsed = json.loads(j)
                print(f"\n파싱된 타입: {type(parsed)}")
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        print(f"  {k}: {type(v)}")
                        if isinstance(v, list):
                            print(f"    len={len(v)}, 첫 항목: {str(v[0])[:200] if v else 'empty'}")


if __name__ == "__main__":
    asyncio.run(main())
