#!/usr/bin/env python3
"""
NotebookLM → LLM-Wiki 동기화 감시 스크립트
- 일정 간격으로 notebooklm source list를 조회
- 새로 추가된 소스의 fulltext를 추출해 wiki/raw/에 저장
- 중복 저장 방지 (이미 저장된 소스는 건너뜀)
"""

import os
import re
import sys
import json
import time
import hashlib
import datetime
import subprocess
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict

# Windows 콘솔(cp949)에서 이모지 출력 시 UnicodeEncodeError 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ─── Configuration ─────────────────────────────────────────────────────────── #
NOTEBOOKLM_BIN = "notebooklm"

_raw_wiki = os.environ.get("WIKI_PATH", os.path.expanduser("~/wiki"))
WIKI_PATH = Path(os.path.expandvars(_raw_wiki)).resolve()
STATE_FILE = WIKI_PATH / ".notebooklm_sync_state.json"
ATOMIC_RULES_FILE = WIKI_PATH / "atomic_note_rules.md"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# ─── Helper Functions ──────────────────────────────────────────────────────── #

def refresh_auth():
    """Best-effort refresh of notebooklm cookies so auth doesn't drop mid-run.

    Auth is cookie-based (Google); `notebooklm auth refresh` re-exercises the auth
    path using stored cookies and does not normally re-prompt interactively.
    """
    try:
        subprocess.run(
            [NOTEBOOKLM_BIN, "auth", "refresh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as e:
        print(f"⚠️ notebooklm auth refresh failed (continuing): {e}")


_AUTH_HINTS = (
    "unauthorized", "401", "403", "not logged in", "not authenticated",
    "login required", "please login", "please log in", "to login",
    "re-authenticate", "reauth", "missing required cookies",
    "authentication required", "session expired", "expired", "token",
)


def _looks_like_auth_error(e: subprocess.CalledProcessError) -> bool:
    text = f"{e.stdout}\n{e.stderr}".lower()
    return any(hint in text for hint in _AUTH_HINTS)


def run_notebooklm_command(args: List[str], capture_output: bool = True, env: Optional[dict] = None, retry_auth: bool = True, timeout: int = 120):
    """notebooklm CLI 실행. auth 실패 시 cookies를 갱신하고 한 번 재시도."""
    try:
        return subprocess.run(
            [NOTEBOOKLM_BIN] + args,
            capture_output=capture_output,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"⚠️ 명령어 타임아웃: {' '.join(args)}")
        raise
    except subprocess.CalledProcessError as e:
        if retry_auth and _looks_like_auth_error(e):
            print("🔄 Authentication error detected; refreshing notebooklm cookies and retrying...")
            refresh_auth()
            return subprocess.run(
                [NOTEBOOKLM_BIN] + args,
                capture_output=capture_output,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=timeout,
                env=env,
            )
        print(f"⚠️ CLI 실패: {' '.join(args)}")
        if e.stderr:
            print(f"STDERR: {e.stderr[:500]}")
        raise

def send_slack_message(message: str, webhook_url: Optional[str] = None):
    """Slack Webhook으로 메시지 전송."""
    import urllib.request

    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return
    
    payload = {"text": message[:4000]}  # Slack payload size limit
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data,
                                    headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode()
            if response.status == 200 and "ok" in body.lower():
                return True
    except Exception as e:
        print(f"⚠️ Slack 전송 실패: {e}")
    return False

def compute_sha256(content: str) -> str:
    """콘텐츠의 SHA256 해시 계산."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def load_atomic_note_rules() -> str:
    """Atomic Note 변환 규칙을 매 변환 시 파일에서 로드."""
    if not ATOMIC_RULES_FILE.exists():
        raise FileNotFoundError(f"Atomic Note 규칙 파일이 없습니다: {ATOMIC_RULES_FILE}")
    rules = ATOMIC_RULES_FILE.read_text(encoding="utf-8").strip()
    if not rules:
        raise ValueError(f"Atomic Note 규칙 파일이 비어 있습니다: {ATOMIC_RULES_FILE}")
    return rules


def generate_atomic_note(source_info: Dict, notebook_id: str) -> Optional[str]:
    """지정된 NotebookLM source를 Atomic Note 형식으로 변환.

    규칙 파일(atomic_note_rules.md)이 없거나 비어 있으면 None을 반환한다.
    호출 측은 이 반환값과 무관하게 원문(raw) 저장을 계속 진행하므로, 이 함수가
    전체 동기화를 중단시키지 않는다.
    """
    source_id = source_info.get("id", "")
    title = source_info.get("title", "Untitled")
    source_type = source_info.get("type", "unknown")
    source_url = source_info.get("url", "")
    try:
        rules = load_atomic_note_rules()
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️ Atomic Note 규칙 로드 실패 (Atomic Note 건너뜀): {e}")
        return None

    prompt = f"""다음 NotebookLM source 하나만 사용하여 Atomic Note를 작성하라.

source title: {title}
source type: {source_type}
source id: {source_id}
source url: {source_url}

요구사항:
- 다른 source의 내용을 섞지 말 것.
- 원문에서 확인되지 않는 수치, 인용, 인과관계를 만들지 말 것.
- 원문이 여러 주제를 포함하더라도 가장 중심적인 단일 개념 하나를 선택할 것.
- 설명이나 보고서 서문 없이 Markdown Atomic Note만 출력할 것.

===== Atomic Note 변환 규칙 =====
{rules}
===== 변환 시작 =====
"""
    safe_sid = re.sub(r'[<>:"/\\|?*]', "_", source_id)
    prompt_file = WIKI_PATH / f".atomic_prompt_{safe_sid}.txt"
    try:
        prompt_file.write_text(prompt, encoding="utf-8")
        result = run_notebooklm_command(
            ["ask", "-n", notebook_id, "--prompt-file", str(prompt_file)],
            timeout=300,
        )
        answer = result.stdout.strip()
        if "Answer:" in answer:
            answer = answer.split("Answer:", 1)[1].lstrip()
        if "Resumed conversation:" in answer:
            answer = answer.split("Resumed conversation:", 1)[0].rstrip()
        if "Conversation:" in answer and answer.startswith("Conversation:"):
            answer = answer.split("\n", 1)[1] if "\n" in answer else ""
        if answer.startswith("```"):
            lines = answer.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            answer = "\n".join(lines).strip()
        return answer or None
    except Exception as e:
        print(f"⚠️ Atomic Note 변환 실패: {source_id} - {e}")
        return None
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except Exception:
            pass


def save_atomic_note_to_wiki(source_info: Dict, atomic_note: str, notebook_id: str, replace: bool = False):
    """생성된 Atomic Note를 wiki/raw/에 저장.

    replace=True이면 source ID 기반의 고정 파일명을 사용해 재생성 시 기존
    Atomic Note를 교체한다.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    title = source_info.get("title", "Untitled")
    source_id = source_info.get("id", "unknown")
    safe_title = "".join(c if c.isalnum() else "_" for c in title)[:80]
    safe_sid = re.sub(r'[<>:"/\\|?*]', "_", source_id)
    if replace:
        filename = WIKI_PATH / "raw" / f"atomic_{safe_title}_{safe_sid}.md"
    else:
        filename = WIKI_PATH / "raw" / f"atomic_{safe_title}_{timestamp}.md"
    filename.parent.mkdir(parents=True, exist_ok=True)
    if not replace:
        counter = 1
        base = filename
        while filename.exists():
            filename = base.parent / f"{base.stem}_{counter}{base.suffix}"
            counter += 1
    filename.write_text(atomic_note.rstrip() + "\n", encoding="utf-8")
    print(f"✅ Atomic Note 저장됨: {filename}")
    return filename


def load_state() -> Dict:
    """이전 동기화 상태 로드."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
            return data
        except Exception:
            pass
    return {}

def save_state(state: Dict):
    """동기화 상태 저장."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def update_state(updates: Dict):
    """기존 상태를 유지하면서 일부 필드만 갱신 (synced_sources 보존)."""
    state = load_state()
    state.update(updates)
    save_state(state)

def source_exists_in_wiki(source_id: str, source_type: str, notebook_id: str) -> bool:
    """이미 sync에 기록된 소스인지 확인 (notebook 기준)."""
    state = load_state()
    synced = state.get("synced_sources", [])
    # 신·구 키 형식을 모두 수용하여 포맷 변경 전 상태 파일도 중복 방지됨
    key = f"{notebook_id}:{source_type}:{source_id}"
    old_key = f"{source_type}:{source_id}"
    return key in synced or old_key in synced

def mark_source_synced(source_id: str, source_type: str, notebook_id: str):
    """소스 동기화 기록."""
    state = load_state()
    if "synced_sources" not in state:
        state["synced_sources"] = []
    
    key = f"{notebook_id}:{source_type}:{source_id}"
    if key not in state["synced_sources"]:
        state["synced_sources"].append(key)
        state["last_sync"] = datetime.datetime.now().isoformat()
    save_state(state)

def save_source_to_wiki(source_info: Dict, fulltext: str, notebook_id: str):
    """소스 메타데이터를 wiki/raw/에 저장."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    source_type = source_info.get("type", "unknown")
    source_id = source_info.get("id", "unknown")
    title = source_info.get("title", source_info.get("url", "Untitled"))
    source_url = source_info.get("url", "")
    
    # 안전한 파일명 생성
    safe_title = "".join(c if c.isalnum() else "_" for c in title)[:80]
    filename = WIKI_PATH / "raw" / f"{source_type}_{safe_title}_{timestamp}.md"
    filename.parent.mkdir(parents=True, exist_ok=True)
    
    # 이미 존재하면 다른 이름으로 저장 시도
    base = filename
    counter = 1
    while filename.exists():
        name = base.stem
        suffix = base.suffix
        filename = base.parent / f"{name}_{counter}{suffix}"
        counter += 1
    
    sha256_hash = compute_sha256(fulltext)
    
    # frontmatter + 본문 작성
    content = []
    content.append("---")
    content.append(f"source_type: {source_type}")
    content.append(f"source_id: {source_id}")
    content.append(f"notebook_id: {notebook_id}")
    content.append(f"source_url: {source_url}")
    content.append(f"ingested: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    content.append(f"sha256: {sha256_hash}")
    content.append("---")
    content.append("")
    content.append(f"# {title}")
    content.append("")
    content.append(f"## 원본 소스 정보")
    content.append("")
    content.append(f"- **유형**: {source_type}")
    content.append(f"- **ID**: `{source_id}`")
    content.append(f"- **Notebook**: `{notebook_id}`")
    content.append(f"- **URL**: {source_url}")
    content.append(f"- **저장소 가져오기**: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    content.append("")
    content.append("---")
    content.append("")
    content.append("## 전체 텍스트")
    content.append("")
    content.append(fulltext)
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("\n".join(content))
    
    print(f"✅ 저장됨: {filename}")
    return filename

def get_all_notebooks() -> List[Dict]:
    """사용자의 모든 NotebookLM 노트북 목록 조회."""
    try:
        result = run_notebooklm_command(["list", "--json"])
        data = json.loads(result.stdout)
        notebooks = data.get("notebooks", [])
        return notebooks
    except Exception as e:
        print(f"⚠️ 노트북 목록 조회 실패: {e}")
        return []

def get_notebook_sources(notebook_id: str) -> List[Dict]:
    """특정 노트북의 모든 소스 조회 (notebooklm source list -n <id> --json).

    `source list`는 -n 플래그로 노트북을 지정할 수 있으므로, 전역 컨텍스트를
    변경하는 `use` 대신 -n을 사용한다.
    """
    try:
        result = run_notebooklm_command(["source", "list", "-n", notebook_id, "--json"])
        data = json.loads(result.stdout)
        sources = data.get("sources", [])
        return sources
    except Exception as e:
        print(f"⚠️ 소스 목록 조회 실패 (notebook={notebook_id}): {e}")
        return []

def get_source_fulltext(notebook_id: str, source_id: str) -> Optional[str]:
    """개별 소스의 전체 텍스트 추출 (notebooklm source fulltext <id> -n <nb> --json)."""
    try:
        result = run_notebooklm_command(
            ["source", "fulltext", source_id, "-n", notebook_id, "--json"]
        )
        data = json.loads(result.stdout)
        fulltext = data.get("content", "")
        return fulltext if fulltext else None
    except Exception as e:
        print(f"⚠️ 소스 전체 텍스트 추출 실패: {source_id} - {e}")
        return None

def rebuild_atomic_notes(notebook_id_filter: Optional[str] = None, dry_run: bool = False, limit: int = 0, source_types: Optional[set] = None) -> Dict:
    """이미 동기화된 source의 Atomic Note를 일괄 재생성."""
    state = load_state()
    recorded = set(state.get("synced_sources", []))
    source_types = source_types or {"pdf", "markdown", "web_page", "unknown"}
    notebooks = get_all_notebooks()
    result = {"selected": 0, "rebuilt": 0, "failed": 0, "files": []}

    for notebook in notebooks:
        notebook_id = notebook.get("id", "")
        notebook_title = notebook.get("title", "Unknown")
        if notebook_id_filter and not (
            notebook_id == notebook_id_filter
            or notebook_id.startswith(notebook_id_filter)
            or notebook_title == notebook_id_filter
        ):
            continue
        sources = get_notebook_sources(notebook_id)
        for source in sources:
            source_id = source.get("id", "")
            source_type = source.get("type", "unknown")
            status = source.get("status", "unknown")
            key = f"{notebook_id}:{source_type}:{source_id}"
            old_key = f"{source_type}:{source_id}"
            # 구 키({type}:{id})로 기록된 소스도 재생성 대상에 포함 (sync_notebook과 대칭)
            if (key not in recorded and old_key not in recorded) or source_type not in source_types:
                continue
            if status in {"processing", "error"}:
                print(f"⏭️ 건너뜀({status}): {source.get('title', source_id)}")
                continue
            if limit and result["selected"] >= limit:
                return result
            result["selected"] += 1
            title = source.get("title", source_id)
            print(f"\n🔁 Atomic Note 재생성: {title} ({source_type})")
            if dry_run:
                continue
            atomic_note = generate_atomic_note(source, notebook_id)
            if not atomic_note:
                result["failed"] += 1
                continue
            filename = save_atomic_note_to_wiki(source, atomic_note, notebook_id, replace=True)
            result["rebuilt"] += 1
            result["files"].append(str(filename))
    return result


def sync_notebook(notebook: Dict, dry_run: bool = False) -> List[str]:
    """단일 노트북의 새 소스를 감지하고 동기화."""
    notebook_id = notebook.get("id", "")
    notebook_title = notebook.get("title", "Unknown")
    
    print(f"\n📓 노트북 확인: {notebook_title} ({notebook_id})")
    
    sources = get_notebook_sources(notebook_id)
    if not sources:
        print(f"   ⚠️ 소스 없음 또는 조회 실패")
        return []
    
    synced_files = []
    new_sources = []
    
    for source in sources:
        source_id = source.get("id", "")
        source_type = source.get("type", "unknown")
        title = source.get("title", "Untitled")
        
        # 이미 sync된 소스는 건너뜀
        if source_exists_in_wiki(source_id, source_type, notebook_id):
            continue
        
        # 상태가 processing/error이면 건너뜀
        status = source.get("status", "unknown")
        if status == "processing":
            print(f"   ⏳ 처리 중: {title} ({source_id}) - 건너뜀")
            continue
        elif status == "error":
            print(f"   ❌ 처리 오류: {title} ({source_id}) - 건너뜀")
            continue
        
        # fulltext 추출 시도
        print(f"   🔍 새로운 소스 발견: {title} ({source_id})")
        
        if dry_run:
            print(f"   [DRY RUN] 전체 텍스트 추출 생략")
            new_sources.append(source)
            continue
        
        fulltext = get_source_fulltext(notebook_id, source_id)
        
        if fulltext:
            # 원문(raw)은 항상 먼저 저장한다. Atomic Note는 파생 산물이므로
            # 실패하더라도 원문 손실이 없도록 한다.
            filename = save_source_to_wiki(source, fulltext, notebook_id)
            synced_files.append(str(filename))
            new_sources.append(source)
            mark_source_synced(source_id, source_type, notebook_id)

            atomic_note = generate_atomic_note(source, notebook_id)
            if atomic_note:
                atomic_filename = save_atomic_note_to_wiki(source, atomic_note, notebook_id, replace=True)
                send_slack_message(
                    f"📥 NotebookLM 동기화 완료\n"
                    f"   노트북: {notebook_title}\n"
                    f"   소스: {title}\n"
                    f"   유형: {source_type}\n"
                    f"   원문 파일: {Path(filename).name}\n"
                    f"   Atomic Note: {Path(atomic_filename).name}"
                )
            else:
                print(f"   ⚠️ Atomic Note 생성 실패 - 원문은 저장됨 (rebuild-atomic로 재생성 가능)")
        else:
            print(f"   ⚠️ 전체 텍스트 추출 실패 (빈 콘텐츠 또는 오류) - 이 소스는 다음 동기화에서 재시도됨")
    
    return synced_files

def sync_all_notebooks(dry_run: bool = False, notebook_id_filter: Optional[str] = None) -> Dict:
    """모든 노트북을 순회하면서 새 소스를 동기화."""
    notebooks = get_all_notebooks()
    
    if not notebooks:
        print("⚠️ 조회 가능한 노트북이 없습니다.")
        return {"synced": 0, "skipped": 0, "files": [], "notebooks": []}
    
    print(f"\n📚 총 {len(notebooks)}개 노트북 확인 시작")
    
    summary = {
        "synced": 0,
        "skipped": 0,
        "files": [],
        "notebooks": []
    }
    
    for notebook in notebooks:
        nid = notebook.get("id", "")
        ntitle = notebook.get("title", "")
        
        if notebook_id_filter and nid != notebook_id_filter and ntitle != notebook_id_filter:
            continue
        
        print(f"\n{'='*60}")
        print(f"📓 {ntitle} ({nid})")
        print(f"{'='*60}")
        
        files = sync_notebook(notebook, dry_run=dry_run)
        if files:
            summary["synced"] += len(files)
            summary["files"].extend(files)
            summary["notebooks"].append(ntitle)
        else:
            summary["skipped"] += 1
    
    return summary

def print_summary(summary: Dict, dry_run: bool = False):
    """동기화 결과 요약 출력."""
    mode = "[DRY RUN] " if dry_run else ""
    
    print(f"\n{'='*60}")
    print(f"📊 동기화 결과 요약 {mode}")
    print(f"{'='*60}")
    print(f"   동기화 성공: {summary['synced']}개 소스")
    print(f"   건너뜀: {summary['skipped']}개 노트북")
    
    if summary['files']:
        print(f"\n   저장된 파일:")
        for f in summary['files']:
            print(f"      - {Path(f).name}")
    
    if summary['notebooks']:
        print(f"\n   대상 노트북: {', '.join(summary['notebooks'])}")
    
    # Slack 알림
    if summary['synced'] > 0:
        slack_msg = (
            f"📥 **NotebookLM → LLM-wiki 동기화 완료** {mode}\n\n"
            f"   새로 저장된 소스: {summary['synced']}개\n"
            f"   대상 노트북: {len(summary['notebooks'])}개\n\n"
            f"   저장된 파일:\n"
        )
        for f in summary['files'][:5]:  # 최대 5개 표시
            slack_msg += f"   - {Path(f).name}\n"
        if len(summary['files']) > 5:
            slack_msg += f"   ... 및 {len(summary['files']) - 5}개 더\n"
        
        send_slack_message(slack_msg)

# ─── CLI Interface ──────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="NotebookLM → LLM-Wiki 소스 동기화 감시 스크립트"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="실행 모드")
    
    # 단일 실행
    single_parser = subparsers.add_parser("sync", help="단일 실행: 새 소스 감지 및 저장")
    single_parser.add_argument(
        "--notebook", "-n", 
        help="특정 노트북만 동기화 (ID 또는 제목)"
    )
    single_parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="실제 저장 없이 감지 결과만 출력"
    )

    # 기존 source의 Atomic Note 일괄 재생성
    rebuild_parser = subparsers.add_parser(
        "rebuild-atomic", help="기존에 동기화된 source의 Atomic Note 일괄 재생성"
    )
    rebuild_parser.add_argument(
        "--notebook", "-n", help="특정 노트북만 재생성 (ID 또는 제목)"
    )
    rebuild_parser.add_argument(
        "--dry-run", "-d", action="store_true", help="대상 목록만 확인"
    )
    rebuild_parser.add_argument(
        "--limit", type=int, default=0, help="처리할 최대 source 수 (0=전체)"
    )
    rebuild_parser.add_argument(
        "--types", default="pdf,markdown,web_page,unknown",
        help="대상 source 유형을 쉼표로 지정"
    )
    
    # 데몬 모드 (주기적 감시)
    daemon_parser = subparsers.add_parser("daemon", help="백그라운드 감시: 주기적 동기화")
    daemon_parser.add_argument(
        "--interval", "-i",
        type=int,
        default=300,
        help="폴링 간격 (초, 기본값: 300초 = 5분)"
    )
    daemon_parser.add_argument(
        "--max-runs", "-m",
        type=int,
        default=0,
        help="최대 실행 횟수 (0 = 무한)"
    )
    daemon_parser.add_argument(
        "--notebook", "-n",
        help="특정 노트북만 감시"
    )
    daemon_parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="요청이 있을 때만 알림 (기본: 매번 알림)"
    )
    
    # 상태 확인
    status_parser = subparsers.add_parser("status", help="동기화 상태 확인")
    
    # 상태 초기화
    reset_parser = subparsers.add_parser("reset", help="동기화 기록 초기화")
    reset_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="확인 없이 초기화"
    )
    
    args = parser.parse_args()
    mode_label = f"[명령: {args.command}]" if args.command else "[전체 루프]"
    
    if args.command == "sync":
        print(f"{mode_label} NotebookLM → LLM-Wiki 단일 동기화 시작")
        
        summary = sync_all_notebooks(
            dry_run=args.dry_run,
            notebook_id_filter=args.notebook
        )
        print_summary(summary, dry_run=args.dry_run)
        
        # 상태 파일 갱신 (synced_sources 보존)
        state = load_state()
        update_state({
            "last_sync": datetime.datetime.now().isoformat(),
            "total_synced": len(state.get("synced_sources", [])),
            "notebooks_synced": summary['notebooks']
        })
        
    elif args.command == "rebuild-atomic":
        print(f"{mode_label} 기존 Atomic Note 일괄 재생성 시작")
        types = {item.strip() for item in args.types.split(",") if item.strip()}
        result = rebuild_atomic_notes(
            notebook_id_filter=args.notebook,
            dry_run=args.dry_run,
            limit=args.limit,
            source_types=types,
        )
        print("\n" + "=" * 60)
        print("📊 Atomic Note 재생성 결과")
        print("=" * 60)
        print(f"   대상 source: {result['selected']}개")
        print(f"   재생성 성공: {result['rebuilt']}개")
        print(f"   실패: {result['failed']}개")
        if result["files"]:
            print("   저장 파일 예시:")
            for filename in result["files"][:10]:
                print(f"      - {Path(filename).name}")

    elif args.command == "daemon":
        print(f"{mode_label} 백그라운드 감시 시작")
        print(f"   폴링 간격: {args.interval}초")
        if args.max_runs > 0:
            print(f"   최대 실행: {args.max_runs}회")
        if args.notebook:
            print(f"   대상 노트북: {args.notebook}")
        print()
        
        run_count = 0
        last_alert_time = 0
        ALERT_COOLDOWN = 3600  # 1시간 간격
        
        while True:
            run_count += 1
            print(f"\n🔄 실행 #{run_count} 시작 ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
            
            summary = sync_all_notebooks(
                dry_run=False,
                notebook_id_filter=args.notebook
            )
            
            # 알림 조건: 새로운 소스가 있거나 quiet 모드가 아닌 경우
            if summary['synced'] > 0 and (not args.quiet or time.time() - last_alert_time > ALERT_COOLDOWN):
                print_summary(summary, dry_run=False)
                last_alert_time = time.time()
            elif args.quiet and summary['synced'] == 0:
                print("   새로운 소스 없음 (알림 생략)")
            else:
                print("   새로운 소스 없음")
            
            # 상태 업데이트 (synced_sources 보존)
            state = load_state()
            update_state({
                "last_sync": datetime.datetime.now().isoformat(),
                "last_run": run_count,
                "total_synced": len(state.get("synced_sources", [])),
                "last_summary": {
                    "synced": summary['synced'],
                    "skipped": summary['skipped']
                }
            })
            
            # 종료 조건 확인
            if args.max_runs > 0 and run_count >= args.max_runs:
                print(f"\n🏁 최대 실행 횟수({args.max_runs}회)에 도달. 종료.")
                break
            
            # 다음 폴링까지 대기
            print(f"\n⏳ 다음 폴링까지 {args.interval}초 대기...")
            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n⛔ 사용자에 의해 중단.")
                break
        
        print("\n✅ 감시 종료.")
        update_state({
            "last_sync": datetime.datetime.now().isoformat(),
            "last_run": run_count,
            "status": "stopped"
        })
        
    elif args.command == "status":
        print(f"{mode_label} 현재 동기화 상태")
        print()
        
        # 상태 파일 확인
        if STATE_FILE.exists():
            data = load_state()
            print(f"👁️ 상태 파일: {STATE_FILE}")
            print(f"   마지막 동기화: {data.get('last_sync', '없음')}")
            print(f"   마지막 실행 횟수: {data.get('last_run', '없음')}")
            print(f"   총 동기화 수: {data.get('total_synced', 0)}")
            
            synced = data.get("synced_sources", [])
            print(f"   기록된 소스: {len(synced)}개")
            if synced:
                print("   소스 목록:")
                for s in synced[-10:]:  # 최근 10개
                    print(f"      - {s}")
        else:
            print("👁️ 상태 파일을 찾을 수 없습니다 (아직 동기화가 실행되지 않음)")
        
        # 현재 노트북 목록
        notebooks = get_all_notebooks()
        print(f"\n📚 현재 노트북 ({len(notebooks)}개):")
        for nb in notebooks:
            nid = nb.get("id", "")
            ntitle = nb.get("title", "")
            sources = get_notebook_sources(nid)
            print(f"   - {ntitle} ({len(sources)}개 소스)")
        
        print("\n💡 동기화 실행: notebooklm-wiki-sync.py sync")
        print("💡 데몬 모드: notebooklm-wiki-sync.py daemon")
        
    elif args.command == "reset":
        if args.yes:
            if STATE_FILE.exists():
                STATE_FILE.unlink()
                print("✅ 동기화 기록이 초기화되었습니다.")
            else:
                print("⚠️ 상태 파일이 이미 없습니다.")
        else:
            print("⚠️ 동기화 기록을 초기화하려면 --yes 옵션을 추가하세요.")
            print("   예: notebooklm-wiki-sync.py reset --yes")
        
    else:
        parser.print_help()
