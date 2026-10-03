#!/usr/bin/env python3
"""
scite MCP OAuth 2.0 인증 스크립트 (PKCE S256)
- 로컬 HTTP 서버로 code 수신
- code + code_verifier → access_token 교환
- 토큰을 ~/.hermes/.env에 저장 (SCITE_ACCESS_TOKEN 등)

두 가지 모드:
  1) 기본: PKCE로 새 인증 URL을 만들고 브라우저 열림 → 승인 후 자동 토큰 교환
  2) 수동: 이미 받은 authorization code를 첫 인자로 전달 → 바로 토큰 교환
     예: python scite_oauth_auth.py "https://.../callback?code=..."
"""

import asyncio
import base64
import hashlib
import secrets
import sys
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────────────
CLIENT_ID     = "oauth_HfhgVhltn0c5mR2fU_Jysg"
REDIRECT_URI  = "http://localhost:9999/callback"
AUTH_URL      = "https://api.scite.ai/mcp/oauth/authorize"
TOKEN_URL     = "https://api.scite.ai/mcp/oauth/token"
SCOPE         = "mcp"
PORT          = 9999
CODE_CHALLENGE_METHOD = "S256"

HERMES_HOME = Path.home() / ".hermes"
ENV_FILE    = HERMES_HOME / ".env"

# ── PKCE helpers ──────────────────────────────────────────────────────
def make_code_verifier() -> str:
    return secrets.token_urlsafe(64)

def compute_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── 로컬 리다이렉트 핸들러 ────────────────────────────────────────────
class AuthHandler(BaseHTTPRequestHandler):
    captured_code = None

    def log_message(self, fmt, *args):
        pass  # 조용

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/callback" and "code" in params:
            AuthHandler.captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                """<html><body style="font-family:sans-serif;padding:40px;text-align:center;">
                <h2>✅ 인증 완료</h2><p>액세스 토큰을 획득했습니다. 창이 자동으로 닫힙니다.</p>
                <script>setTimeout(()=>window.close(),1500);</script></body></html>""".encode()
            )
            print("\n[서버] 인증 코드 수신 완료")
        else:
            self.send_response(404)
            self.end_headers()


# ── 토큰 교환 ─────────────────────────────────────────────────────────
async def exchange_token(code: str, code_verifier: str) -> dict | None:
    import httpx
    print(f"\n[토큰 교환] code_verifier 사용...")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": code_verifier,
            },
            timeout=30.0,
        )
    if resp.status_code != 200:
        print(f"[오류] 토큰 교환 실패 (HTTP {resp.status_code})")
        # 실패 응답에서 민감한 정보 제외
        error_text = resp.text[:500]
        # 토큰 유사 문자열 마스킹
        import re
        error_text = re.sub(r'"access_token"\s*:\s*"[^"]*"', '"access_token": "***"', error_text)
        error_text = re.sub(r'"refresh_token"\s*:\s*"[^"]*"', '"refresh_token": "***"', error_text)
        print(error_text)
        return None
    data = resp.json()
    # 토큰 길이만 표시하고 실제 값은 마스킹
    access_token = data.get('access_token', '')
    print(f"  access_token: *** (길이 {len(access_token)})")
    print(f"  expires_in: {data.get('expires_in')}초")
    if data.get("refresh_token"):
        print(f"  refresh_token: *** (길이 {len(data['refresh_token'])})")
    return data


# ── .env 저장 ─────────────────────────────────────────────────────────
def save_to_env(token_data: dict):
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if ENV_FILE.exists():
        # 인코딩 문제 대비: 여러 인코딩 시도
        raw = None
        for enc in ("utf-8", "utf-8-sig", "utf-16-le", "cp949", "cp1252"):
            try:
                raw = ENV_FILE.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if raw is not None:
            for line in raw.splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        else:
            print(f"  [경고] 기존 .env 파일을 읽을 수 없어 새로 작성합니다.")
    existing["SCITE_ACCESS_TOKEN"] = token_data.get("access_token", "")
    if token_data.get("refresh_token"):
        existing["SCITE_REFRESH_TOKEN"] = token_data["refresh_token"]
    import time
    existing["SCITE_TOKEN_EXPIRES_AT"] = str(time.time() + token_data.get("expires_in", 3600))
    existing["SCITE_CLIENT_ID"] = CLIENT_ID
    lines = ["# Scite MCP OAuth 토큰 (PKCE 수동 등록)"]
    for k, v in existing.items():
        lines.append(f"{k}={v}")
    # 원자적 저장: temp 파일 → rename
    tmp_path = ENV_FILE.with_suffix(".tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp_path.replace(ENV_FILE)
    print(f"\n[저장] {ENV_FILE}에 토큰 저장 완료")
    print(f"  SCITE_ACCESS_TOKEN 길이: {len(token_data.get('access_token',''))}")


# ── 메인: 자동 브라우저 모드 ──────────────────────────────────────────
async def run_auto(code_verifier: str, code_challenge: str):
    auth_params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": "scite-mcp-auth",
        "code_challenge": code_challenge,
        "code_challenge_method": CODE_CHALLENGE_METHOD,
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    print("=" * 60)
    print("  Scite MCP PKCE 인증 (자동)")
    print("=" * 60)
    print(f"\n[1] 인증 URL:")
    print(f"  {auth_url}")
    print(f"\n[2] 로컬 서버: http://localhost:{PORT}/callback")

    server = HTTPServer(("127.0.0.1", PORT), AuthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        import webbrowser
        webbrowser.open(auth_url)
        print("[3] 브라우저 자동 열림 → 로그인 & 승인")
    except Exception as e:
        print(f"[3] 브라우저 자동 열기 실패: {e}")
        print(f"   → 위 URL을 직접 브라우저에 붙여넣으세요.")

    print("\n   대기 중... (승인하면 자동 진행)")
    for _ in range(120):
        if AuthHandler.captured_code:
            break
        await asyncio.sleep(1)
    else:
        print("\n[오류] 타임아웃: 인증 코드를 받지 못했습니다.")
        server.shutdown()
        return

    code = AuthHandler.captured_code
    server.shutdown()
    print(f"\n[4] 받은 code: {code[:30]}...")
    token_data = await exchange_token(code, code_verifier)
    if token_data:
        save_to_env(token_data)
        print("\n" + "=" * 60)
        print("  ✅ 인증 완료! 이제 MCP 도구 디스커버리를 실행할 수 있습니다.")
        print("=" * 60)


# ── 메인: 수동 코드 모드 ──────────────────────────────────────────────
async def run_manual(auth_url_with_code: str, code_verifier: str):
    """이미 받은 callback URL을 그대로 사용"""
    parsed = urllib.parse.urlparse(auth_url_with_code)
    params = urllib.parse.parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    if not code:
        print("[오류] URL에서 code 파라미터를 찾을 수 없습니다.")
        return
    print("=" * 60)
    print("  Scite MCP PKCE 인증 (수동 코드)")
    print("=" * 60)
    print(f"\n[받은 code]: {code[:40]}...")
    token_data = await exchange_token(code, code_verifier)
    if token_data:
        save_to_env(token_data)
        print("\n" + "=" * 60)
        print("  ✅ 인증 완료!")
        print("=" * 60)


# ── 진입점 ────────────────────────────────────────────────────────────
async def main():
    if len(sys.argv) > 1:
        url = sys.argv[1]
        cv = os.environ.get("SCITE_CODE_VERIFIER")
        if not cv:
            print("[오류] SCITE_CODE_VERIFIER 환경변수가 설정되지 않았습니다.")
            print("  이전 실행에서 출력된 code_verifier 값을 이 변수에 설정하고 다시 실행하세요.")
            print("  예: set SCITE_CODE_VERIFIER=...  (Windows cmd)")
            print("  예: export SCITE_CODE_VERIFIER=...  (bash/MSYS)")
            return
        await run_manual(url, cv)
    else:
        # 자동 모드
        cv = make_code_verifier()
        cc = compute_code_challenge(cv)
        # code_verifier를 .env에도 미리 저장해두면 나중에 수동 모드에서 사용 가능
        os.environ["SCITE_CODE_VERIFIER"] = cv
        await run_auto(cv, cc)

if __name__ == "__main__":
    asyncio.run(main())
