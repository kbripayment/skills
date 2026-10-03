#!/usr/bin/env python3
"""scite MCP 도구 디스커버리"""

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
        print("❌ SCITE_ACCESS_TOKEN을 찾을 수 없습니다.")
        print("   ~/.hermes/.env에 SCITE_ACCESS_TOKEN이 설정되어 있는지 확인하세요.")
        return

    print(f"✅ 토큰 로드 완료 (길이: {len(token)})")
    url = "https://api.scite.ai/mcp"
    headers = {"Authorization": f"Bearer {token}"}

    # http_client를 직접 만들어서 전달
    import httpx
    client = httpx.AsyncClient(
        base_url=url,
        headers=headers,
        timeout=30.0,
    )
    async with streamable_http_client(url, http_client=client) as streams:
        read, write = streams
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"\n{'='*60}")
            print(f"  Scite MCP 도구 목록 ({len(tools.tools)}개)")
            print(f"{'='*60}")
            for t in tools.tools:
                print(f"\n🔧 [{t.name}]")
                print(f"   설명: {t.description}")
                if t.input_schema and t.input_schema.get("properties"):
                    for pname, pinfo in t.input_schema["properties"].items():
                        req = "※필수" if pname in t.input_schema.get("required", []) else ""
                        pt = pinfo.get("type", "?")
                        pd = pinfo.get("description", "")
                        print(f"   ├─ {pname}: {pt} {req}")
                        if pd:
                            print(f"   │  └ {pd[:120]}")
            print(f"\n{'='*60}")
            tool_names = [t.name for t in tools.tools]
            print(f"도구 이름: {json.dumps(tool_names, ensure_ascii=False)}")
            return tool_names


if __name__ == "__main__":
    result = asyncio.run(main())
