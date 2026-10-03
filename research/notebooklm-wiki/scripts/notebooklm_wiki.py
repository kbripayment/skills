#!/usr/bin/env python3
"""
NotebookLM Wiki Integration Script

Automates the workflow between Google NotebookLM and the LLM-wiki knowledge base system.
"""

import os
import subprocess
import json
import hashlib
import datetime
from pathlib import Path
from typing import List, Optional

# ─── Configuration ─────────────────────────────────────────────────────────── #
WIKI_PATH = Path(os.environ.get("WIKI_PATH", os.path.expanduser("~/wiki")))
NOTEBOOKLM_BIN = "notebooklm"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# ─── Slack Helper ───────────────────────────────────────────────────────────── #
def send_slack_message(message: str, webhook_url: Optional[str] = None):
    """Send a message to Slack via webhook."""
    import urllib.request
    
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        print("⚠️ SLACK_WEBHOOK_URL not set. Skipping Slack notification.")
        return
    
    payload = {"text": message}
    
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url,
                                    data=data,
                                    headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            # Slack incoming webhooks reply with plain text "ok", not JSON.
            body = response.read().decode()
            if response.status == 200 and "ok" in body.lower():
                print("✅ Slack message sent successfully.")
            else:
                print(f"⚠️ Slack response: {body}")
    except Exception as e:
        print(f"⚠️ Failed to send Slack message: {e}")

# ─── Helper Functions ─────────────────────────────────────────────────────── #

def refresh_auth():
    """Best-effort refresh of notebooklm cookies so auth doesn't drop mid-run.

    Auth is cookie-based (Google). `notebooklm auth refresh` re-exercises the auth
    path using stored cookies; it does not re-prompt interactively in normal use.
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


def run_notebooklm_command(args: List[str], capture_output: bool = True, env: Optional[dict] = None, retry_auth: bool = True) -> subprocess.CompletedProcess:
    """Run a notebooklm CLI command and return the result.

    On an auth-looking failure, refresh cookies once and retry before giving up.
    """
    try:
        return subprocess.run(
            [NOTEBOOKLM_BIN] + args,
            capture_output=capture_output,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        if retry_auth and _looks_like_auth_error(e):
            print("🔄 Authentication error detected; refreshing notebooklm cookies and retrying...")
            refresh_auth()
            return subprocess.run(
                [NOTEBOOKLM_BIN] + args,
                capture_output=capture_output,
                text=True,
                check=True,
                env=env,
            )
        print(f"Command failed: {' '.join(args)}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        raise

def save_to_wiki_raw(file_path: Path, content: str, source_url: Optional[str] = None):
    """Save extracted content to the LLM-wiki raw layer with frontmatter."""
    raw_dir = WIKI_PATH / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    filename = file_path.stem + ".md"
    save_path = raw_dir / filename

    if save_path.exists():
        print(f"⚠️ {save_path} already exists; skipping to avoid overwriting existing raw.")
        return save_path

    # Compute SHA256 of body
    body = content
    sha256_hash = hashlib.sha256(body.encode()).hexdigest()

    # Create frontmatter
    frontmatter_lines = [
        "---",
        f"source_url: {source_url}" if source_url else "",
        f"ingested: {datetime.date.today().isoformat()}",
        f"sha256: {sha256_hash}",
        "---",
        ""
    ]
    frontmatter = "\n".join(frontmatter_lines)
    
    # Write to file
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(frontmatter + body)

    print(f"✅ Saved raw file to wiki: {save_path}")
    return save_path

def create_notebook(title: str) -> str:
    """Create a new NotebookLM notebook and return its ID."""
    result = run_notebooklm_command(["create", title, "--json"])
    data = json.loads(result.stdout)
    notebook_id = data["notebook"]["id"]
    print(f"📝 Created notebook '{title}' with ID: {notebook_id}")
    return notebook_id

def wait_for_sources(notebook_id: str, source_ids: List[str], timeout: int = 600):
    """Wait for all sources to be processed by NotebookLM."""
    for sid in source_ids:
        try:
            run_notebooklm_command(["source", "wait", sid, "-n", notebook_id, "--timeout", str(timeout)])
            print(f"✅ Source {sid} ready.")
        except subprocess.CalledProcessError:
            print(f"❌ Failed to process source {sid}, skipping.")

def generate_artifact(notebook_id: str, artifact_type: str, prompt: str = "", wait: bool = True) -> dict:
    """Generate an artifact in NotebookLM (e.g., quiz, flashcards)."""
    args = ["generate", artifact_type, "-n", notebook_id]
    if prompt:
        if Path(prompt).exists():
            args += ["--prompt-file", prompt]
        else:
            args += [prompt]   # positional DESCRIPTION
    if wait:
        args.append("--wait")

    result = run_notebooklm_command(args + ["--json"])
    data = json.loads(result.stdout)
    print(f"🎨 Generated {artifact_type}: {data.get('artifact_id', data.get('task_id', 'unknown'))}")
    return data

def download_artifact(artifact_id: str, notebook_id: str, output_path: Path, artifact_type: str = "quiz"):
    """Download a generated artifact to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["download", artifact_type, str(output_path), "-n", notebook_id, "--artifact", artifact_id]
    if artifact_type == "quiz":
        cmd.append("--format")
        cmd.append("markdown")
    run_notebooklm_command(cmd)
    print(f"💾 Downloaded artifact to: {output_path}")
def check_notebook_status(notebook_id: str):
    """Check the status of a NotebookLM notebook."""
    env = os.environ.copy()
    env["NOTEBOOKLM_NOTEBOOK"] = notebook_id
    result = run_notebooklm_command(["status", "--json"], env=env)
    data = json.loads(result.stdout)
    print(f"📊 Notebook Status:\n{json.dumps(data, indent=2)}")
    return data

# ─── Workflow Functions ────────────────────────────────────────────────────── #

def start_research_session(topic: str, sources: List[str]):
    """
    Start a research session:
    1. Create a notebook
    2. Add sources
    3. Wait for processing
    4. Save raw materials to wiki
    """
    send_slack_message(f"🚀 Starting research session for: {topic}")
    
    notebook_id = create_notebook(topic)
    send_slack_message(f"📝 Created notebook: {notebook_id}")
    
    source_ids = []
    for src in sources:
        if src.startswith("http") or src.startswith("@url:"):
            result = run_notebooklm_command(["source", "add", src, "-n", notebook_id, "--json"])
            sid = json.loads(result.stdout)["source"]["id"]
            source_ids.append(sid)
            # Extract content and save to wiki
            fulltext = run_notebooklm_command(["source", "fulltext", sid, "-n", notebook_id, "--json"])
            content = json.loads(fulltext.stdout)["content"]
            save_to_wiki_raw(Path(f"{topic.replace(' ', '_')}_{src.split('/')[-1]}"), content, src)
            send_slack_message(f"🔗 Added source: {src}")
        else:
            filepath = Path(src)
            if filepath.exists():
                result = run_notebooklm_command(["source", "add", str(filepath), "-n", notebook_id, "--json"])
                sid = json.loads(result.stdout)["source"]["id"]
                source_ids.append(sid)
                # Save local file to wiki raw
                save_to_wiki_raw(filepath, filepath.read_text(encoding='utf-8'))
                send_slack_message(f"📄 Added local file: {filepath.name}")

    wait_for_sources(notebook_id, source_ids)
    send_slack_message(f"✅ All sources processed for notebook: {notebook_id}")
    return notebook_id

def generate_podcast(notebook_id: str, prompt_file: Optional[str] = None):
    """Generate a podcast from the notebook and download it."""
    result = generate_artifact(notebook_id, "audio", prompt=prompt_file or "Focus on key insights.")
    artifact_id = result.get("task_id") or result.get("artifact", {}).get("id")
    
    if artifact_id:
        download_artifact(artifact_id, notebook_id, WIKI_PATH / "raw" / "assets" / "podcast.mp3", artifact_type="audio")

def generate_quiz(notebook_id: str, output_format: str = "markdown"):
    """Generate a quiz and save it to the wiki."""
    result = generate_artifact(notebook_id, "quiz")
    artifact_id = result.get("task_id") or result.get("artifact", {}).get("id")

    if not artifact_id:
        print("⚠️ No artifact ID returned; skipping quiz download.")
        return

    download_path = WIKI_PATH / "raw" / "assets" / "quiz.md"
    download_artifact(artifact_id, notebook_id, download_path)
    # Register a single wiki note that links to the downloaded artifact
    # (avoids writing the full quiz body twice).
    note = (
        f"# Quiz: Generated from NotebookLM\n\n"
        f"Source: `[[notebooklm::{notebook_id}]]`\n\n"
        f"Artifact: {download_path}\n"
    )
    save_to_wiki_raw(Path(f"quiz_{notebook_id}"), note)

def status_check(notebook_id: str) -> str:
    """Check and report notebook status."""
    status = check_notebook_status(notebook_id)
    summary = status.get("summary", {})
    message = (
        f"📌 **NotebookLM Status Report**\n\n"
        f"Notebook ID: `{notebook_id}`\n"
        f"Sources Processed: {len(summary.get('sources', []))}\n"
        f"Artifacts Generated: {len(summary.get('artifacts', []))}\n"
        f"Last Updated: {summary.get('last_updated', 'Unknown')}"
    )
    print(message)
    send_slack_message(message)
    return message

# ─── Entry Point ─────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NotebookLM x LLM-wiki Integration Tool")
    subparsers = parser.add_subparsers(dest="command")

    # Start research
    start_parser = subparsers.add_parser("start", help="Start a research session")
    start_parser.add_argument("--topic", required=True, help="Research topic")
    start_parser.add_argument("--sources", nargs="+", required=True, help="List of URLs or file paths")

    # Generate podcast
    podcast_parser = subparsers.add_parser("podcast", help="Generate a podcast")
    podcast_parser.add_argument("--notebook-id", required=True)
    podcast_parser.add_argument("--prompt-file", help="Optional prompt file")

    # Generate quiz
    quiz_parser = subparsers.add_parser("quiz", help="Generate a quiz")
    quiz_parser.add_argument("--notebook-id", required=True)

    # Check status
    status_parser = subparsers.add_parser("status", help="Check notebook status")
    status_parser.add_argument("--notebook-id", required=True)

    # Download all artifacts
    download_parser = subparsers.add_parser("download-all", help="Download all artifacts")
    download_parser.add_argument("--notebook-id", required=True)
    download_parser.add_argument("--output-dir", help="Output directory (default: wiki/raw/assets)")

    args = parser.parse_args()

    if args.command == "start":
        nb_id = start_research_session(args.topic, args.sources)
        print(f"🚀 Research session started. Notebook ID: {nb_id}")
    elif args.command == "podcast":
        generate_podcast(args.notebook_id, args.prompt_file)
    elif args.command == "quiz":
        generate_quiz(args.notebook_id)
    elif args.command == "status":
        status_check(args.notebook_id)
    elif args.command == "download-all":
        output_dir = Path(args.output_dir) if args.output_dir else WIKI_PATH / "raw" / "assets"
        env = os.environ.copy()
        env["NOTEBOOKLM_NOTEBOOK"] = args.notebook_id
        run_notebooklm_command(["download", "--all", str(output_dir), "-n", args.notebook_id], env=env)
        print(f"📦 All artifacts downloaded to: {output_dir}")
    else:
        parser.print_help()