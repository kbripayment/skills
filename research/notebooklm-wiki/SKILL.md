---
name: notebooklm-wiki
description: Integrates NotebookLM with LLM-wiki for research automation
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [notebooklm, wiki, research, automation, integration]
category: research
platforms: [linux, macos, windows]
required_commands:
  - notebooklm
  - python
required_environment_variables:
  - WIKI_PATH
---

# NotebookLM Wiki Integration Skill

Two independent wrappers that push external research output into an LLM-wiki:

1. **NotebookLM CLI** (`scripts/notebooklm_wiki.py`) — notebooks, podcasts, quizzes.
2. **Paper search** (`scripts/paper_search_handler.py`, engine in `scripts/paper_search.py`) — PubMed / bioRxiv / Semantic Scholar (+Springer/Elsevier with API keys),
   surfaced via Slack or CLI, with results saved into the wiki.
3. **Multi-repository literature search** (`scripts/paper_search_multi.py`) —
   PubMed / bioRxiv / Semantic Scholar always active; Springer / Elsevier only
   when API keys are set (`SPRINGER_API_KEY` / `ELSEVIER_API_KEY`). Input is a
   keyword; `.csv` / `.pdf` / `.md` are ignored by this module.

This file documents what the scripts actually do. `AGENTS.md` lists behavioral quirks.

> Docs drift note: this file is kept in sync with `scripts/notebooklm_wiki.py`. Do not
> add commands or flags here that are not implemented in the script. `AGENTS.md` lists
> the remaining behavioral quirks (overwrite-prone paths, swallowed source errors, etc.).

## Prerequisites (external, not in this repo)

- The `notebooklm` CLI must be installed, on `PATH`, and authenticated separately.
- `WIKI_PATH` sets the wiki root (default `~/wiki`). `NOTEBOOKLM_PROFILE` is read by docs
  but is **not** used by the script.

## Quick Start

```bash
# Start a research session (--sources is required)
python scripts/notebooklm_wiki.py start --topic "Quantum Computing" --sources "https://arxiv.org/abs/quant-ph/9708027"

# Generate a podcast (--prompt-file optional; defaults to a built-in prompt)
python scripts/notebooklm_wiki.py podcast --notebook-id <ID> --prompt-file ./instructions.txt

# Generate a quiz
python scripts/notebooklm_wiki.py quiz --notebook-id <ID>

# Check status
python scripts/notebooklm_wiki.py status --notebook-id <ID>

# Download every artifact to raw/assets
python scripts/notebooklm_wiki.py download-all --notebook-id <ID>
```

## Architecture

Three components:
1. **NotebookLM CLI** — content ingestion and artifact generation (`notebooklm` binary).
2. **LLM-wiki** — persistent knowledge base the script writes raw notes into via `WIKI_PATH`.
3. **Hermes Scheduler** — for backgrounding long-running tasks (orchestration outside this repo).

The script assumes the `notebooklm` CLI exposes `create`, `source add`/`wait`/`fulltext`,
`generate`, `download`, and `status`, all accepting `--json` and a `-n <notebook-id>` flag.
Verify against the installed CLI before relying on any of them.

## Commands

| Command | Required args | Notes |
|---------|---------------|-------|
|| `start` | `--topic`, `--sources` (1+) | Create notebook, add sources, wait, save raw to wiki |
|| `podcast` | `--notebook-id` | Optional `--prompt-file`; else a default prompt string |
|| `quiz` | `--notebook-id` | Saves artifact + a wiki note |
|| `status` | `--notebook-id` | Prints notebook JSON summary |
|| `download-all` | `--notebook-id` | Optional `--output-dir` (default `WIKI_PATH/raw/assets`) |
|| `sync` (notebooklm-wiki-sync) | `--notebook` (optional), `--dry-run` (optional) | Scan all notebooks for new sources and save to wiki raw layer |
|| `rebuild-atomic` (notebooklm-wiki-sync) | `--notebook` optional, `--dry-run` optional, `--limit` optional, `--types` optional | Rebuild Atomic Notes for already-synced sources; excludes unrecorded and processing/error sources |
|| `daemon` (notebooklm-wiki-sync) | `--interval` (seconds, default 300), `--max-runs`, `--notebook`, `--quiet` | Background polling mode for continuous sync |
|| `status` (notebooklm-wiki-sync) | — | Show sync state (last sync, total synced, recorded sources, current notebooks) |
|| `reset` (notebooklm-wiki-sync) | `--yes` (required) | Reset sync record (state file) |

### Synchronisation commands

|| Command | Required args | Notes |
||---------|---------------|-------|
|| `notebooklm_wiki_sync.sync` | `--notebook` optional `--dry-run` | Scan all notebooks for new sources and save to wiki raw layer |
|| `notebooklm_wiki_sync.daemon` | `--interval` seconds (default 300), `--max-runs`, `--notebook`, `--quiet` | Background polling mode for continuous sync |
|| `notebooklm_wiki_sync.status` | — | Show sync state (last sync, total synced, recorded sources, current notebooks) |
|| `notebooklm_wiki_sync.reset` | `--yes` (required) | Reset sync record (state file) |

### Command details

- **`start`** adds each URL or local file as a source, then for URLs fetches
  `source fulltext` and writes it to the wiki raw layer; local files are copied as-is.
  Sources that fail to process are skipped silently (see Error Handling).
- **`podcast`** generates an audio artifact and downloads it to
  `WIKI_PATH/raw/assets/podcast.mp3` (fixed filename — repeat runs overwrite).
- **`quiz`** generates a quiz, downloads it to `WIKI_PATH/raw/assets/quiz.md`, and writes
  a small linking note to `WIKI_PATH/raw/quiz_<notebook_id>.md`.
- **`status`** prints the raw `notebooklm status --json` output.
- **`download-all`** runs `notebooklm download --all` into the asset directory.

## Workflow Patterns

### Research to Podcast (Automated)
1. `start` creates the notebook and saves sources to the wiki raw layer.
2. `podcast` generates audio and downloads it to `WIKI_PATH/raw/assets/`.
3. `quiz` (optional) generates a quiz and links it from the raw layer.

### NotebookLM → Wiki Sync (Automated source ingestion)
When NotebookLM notebooks are edited from the web UI or from a separate agent, the wiki can
stay in sync with a periodic scan:

1. **One-off scan**: pick up any new sources across all notebooks and write them to `raw/`.
   ```bash
   python scripts/notebooklm_wiki_sync.py sync
   python scripts/notebooklm_wiki_sync.py sync --dry-run        # preview only
   python scripts/notebooklm_wiki_sync.py sync -n "My Research" # single notebook
   ```
2. **Background poll**: keep a daemon running that scans on a fixed interval.
   ```bash
   python scripts/notebooklm_wiki_sync.py daemon --interval 300   # every 5 min
   python scripts/notebooklm_wiki_sync.py daemon -i 600 -m 24     # 10 min, max 24 runs
   python scripts/notebooklm_wiki_sync.py daemon -i 300 -n "X"    # watch one notebook
   python scripts/notebooklm_wiki_sync.py daemon -i 300 -q       # only notify when new sources appear
   ```
3. **Inspect state**: see what has already been synced and what notebooks exist.
   ```bash
   python scripts/notebooklm_wiki_sync.py status
   ```
4. **Reset sync record**: clear the list of already-synced sources (e.g. after a full refresh).
   ```bash
   python scripts/notebooklm_wiki_sync.py reset --yes
   ```

**How it works**: `sync` / `daemon` set the NotebookLM context with `notebooklm use`
then call `notebooklm source list --json` (the installed CLI may reject `-n` on `source list`),
compare IDs against `WIKI_PATH/.notebooklm_sync_state.json`, fetch `source fulltext` for any
new source, and write both the original source-preservation Markdown and an Atomic Note into
`WIKI_PATH/raw/`. Atomic Note generation reads `WIKI_PATH/atomic_note_rules.md` on every
conversion and asks NotebookLM to produce one concept-focused note with frontmatter,
`[[wikilinks]]`, and a source quotation. If Atomic Note generation fails, the source is not
marked synced so the next run retries it. The sync script expands Windows `%VAR%` syntax in
`WIKI_PATH` before constructing paths. Sources in `processing` or `error` status are skipped.
Slack notifications are sent for each notebook that receives new sources when
`SLACK_WEBHOOK_URL` is configured.

**Common pitfalls**
- If no notebook can be listed (or auth is stale), `sync` will print "조회 가능한 노트북이 없습니다" and exit silently. Fix auth with `notebooklm login` and re-run.
- Sources already recorded are skipped; use `reset --yes` to force a fresh full sync.
- Full-text extraction may fail for some source types; the script logs a warning and still marks the source as seen.

### Research Session (library use)
The script exposes module-level functions you can import:
```python
from notebooklm_wiki import start_research_session, generate_quiz, generate_podcast

nb_id = start_research_session("Machine Learning Papers", [
    "https://arxiv.org/abs/cs/12345",
    "./local-presentation.pptx",
])
generate_quiz(nb_id)
generate_podcast(nb_id, prompt_file="./podcast-script.txt")
```
(Import `notebooklm_wiki`, i.e. run from inside `scripts/` or add it to `PYTHONPATH`.)

## File Structure (written by the script)

```
$WIKI_PATH/
├── raw/                          # Saved NotebookLM sources + generated notes
│   └── assets/                   # podcast.mp3, quiz.md (fixed filenames)
└── log.md                        # Not written by this script
```

Note: `save_to_wiki_raw` writes to the **top-level** `raw/` directory, not into an
LLM-wiki topic sub-wiki (`topics/<slug>/`). It skips writing if the target file already
exists, so re-running `start` will not overwrite prior raw files (it warns and continues).

## Error Handling

- Source-processing failures during `start` are caught and skipped (the run still reports
  success). A "successful" session can therefore be missing some sources — check `status`.
- Any non-zero `notebooklm` exit raises after printing stdout/stderr; the script does not
  implement auth refresh or automatic retries.

## Related Skills

- `llm-wiki` — Core knowledge base management
- `obsidian` — Note viewing and editing
- `arxiv` — Academic paper discovery

---

# Multi-Repository Literature Search (`paper_search_multi.py`)

Multiple repositories for a single keyword. Input is a keyword only — `.csv` / `.pdf` / `.md` are ignored by this module.

## Repositories always active

- PubMed (NCBI E-Utilities, 발표일 필터)
- bioRxiv (날짜 범위 + 클라이언트 키워드 필터)
- Semantic Scholar (Graph API, 429/500 재시도)

## Optional repositories (API key needed)

- Springer Nature Open Access (`SPRINGER_API_KEY`)
- Elsevier ScienceDirect (`ELSEVIER_API_KEY`)

API 키가 없으면 해당 저장소는 건너뜁니다 (경고 로그만 남김).

## CLI

```bash
python scripts/paper_search_multi.py <키워드> [max_results] [lookback_days]
```

예:

```bash
python scripts/paper_search_multi.py "microglia Alzheimer" 5 1
python scripts/paper_search_multi.py "hiPSC microglia amyloid" 10 7
```

- `<키워드>`: 공백 포함 가능 (따옴표 권장).
- `max_results`: 각 저장소당 요청 최대치 (기본 5).
- `lookback_days`: PubMed/bioRxiv 날짜 필터 일수 (기본 1). 2020년 이전 논문 등 오래된 문헌을 찾을 때는 `lookback_days=365*5` (5년) 이상으로 설정해야 한다. 기본값은 최근 1일만 검색하므로 대부분의 출간 논문은 누락된다.
- `multi._today_iso()` 함수는 존재하지 않는다 — SKILL.md 예제 코드 중 이 호출은 `date.today().isoformat()` (stdlib `from datetime import date`)로 대체해야 한다. 실사용 시 `AttributeError`가 발생한다.
- Semantic Scholar는 rate-limit(HTTP 429)에 취약하다. 3회 재시도 후에도 실패하면 해당 엔진은 건너뛰므로, 중요 논문은 **PubMed 우선 검색 → Semantic Scholar 보조** 순서를 권장한다. PubMed에 없는 최신 preprint만 Semantic Scholar에 기대할 수 있다.

출력은 저장소별 번호 목록이며, NotebookLM 소스 추가나 LLM-wiki raw 저장으로 연결할 수 있습니다.

## 모듈 임포트 (스크립트 내 재사용)

```python
import sys, os
from pathlib import Path

scripts_dir = Path(os.environ["USERPROFILE"]) / "AppData/Local/hermes/skills/research/notebooklm-wiki/scripts"
sys.path.insert(0, str(scripts_dir))

import paper_search_multi as multi

papers = multi.search_all_repos(
    query="microglia Alzheimer",
    max_results=5,
    lookback_days=1,
    springer_api_key=os.getenv("SPRINGER_API_KEY", ""),
    elsevier_api_key=os.getenv("ELSEVIER_API_KEY", ""),
)

for i, p in enumerate(papers, 1):
    print(f"[{i}] [{p.source}] {p.title}")
    print(f"    URL: {p.url}")
    print(f"    Abstract: {p.abstract[:200]}...")

# Slack/NotebookLM 친화적인 형태로 변환
for d in multi.papers_to_display(papers):
    print(f"  #{d['index']} [{d['source']}] {d['title']}")
```

## NotebookLM 연동 (키워드 검색 → 소스 추가)

검색 결과로 나온 URL을 NotebookLM 노트북에 소스 추가할 수 있습니다:

```bash
# 1. 키워드 검색
python scripts/paper_search_multi.py "microglia Alzheimer" 5 1

# 2. 나온 URL을 NotebookLM에 추가 (예: 3번째 논문 URL 사용)
python scripts/notebooklm_wiki.py start \
    --topic "Microglia Alzheimer Research" \
    --sources "https://pubmed.ncbi.nlm.nih.gov/XXXXX/" "https://www.biorxiv.org/content/..."
```

또는 `notebooklm` CLI를 직접 사용:

```bash
notebooklm create "Microglia Research"
NOTEBOOK_ID=$(notebooklm list --json | jq -r '.notebooks[0].id')
notebooklm source add "https://pubmed.ncbi.nlm.nih.gov/XXXXX/" -n "$NOTEBOOK_ID"
```

## LLM-wiki raw 저장

검생 결과를 위키 raw에 저장하려면 `paper_search_handler.py`의 패턴을 참고하거나,
직접 `paper_to_dict()`/`papers_to_display()` 결과를 markdown으로 작성할 수 있습니다:

```python
import paper_search_multi as multi
from pathlib import Path

papers = multi.search_all_repos("microglia Alzheimer", max_results=5, lookback_days=1)
wiki_raw = Path(os.environ["WIKI_PATH"]) / "raw"

for p in papers:
    safe_name = "".join(c if c.isalnum() else "_" for c in p.title)[:50]
    fname = f"{p.source}_{safe_name}_{multi._today_iso()}.md"
    content = f"""---
source: {p.source}
paper_id: {p.paper_id}
title: {p.title}
url: {p.url}
published_date: {p.published_date}
---

# {p.title}

{p.abstract}
"""
    wiki_raw.joinpath(fname).write_text(content, encoding="utf-8")
```

## API 키 설정

```bash
# .env 또는 환경 변수
export SPRINGER_API_KEY="your-springer-key"
export ELSEVIER_API_KEY="your-elsevier-key"

# Hermes .env (@USERPROFILE%\AppData\Local\hermes\.env)
SPRINGER_API_KEY=your_springer_api_key_here
ELSEVIER_API_KEY=your_elsevier_api_key_here
```

키가 없어도 PubMed/bioRxiv/Semantic Scholar는 계속 동작합니다.

## 실제 워크플로우 예시 (키워드 → NotebookLM → Wiki)

### 시나리오 1: 키워드 검색 → CLI 번호 목록 확인 → NotebookLM 소스 추가

```bash
# 1. 키워드로 검색 (출력을 보고 원하는 논문 URLs 파악)
python scripts/paper_search_multi.py "microglia Alzheimer" 5 1

# 출력 예:
# 📚 키워드 'microglia Alzheimer' 검색 결과 (3건)
# ============================================================
# [1] [PUBMED] Microglial dysregulation in Alzheimer's disease
#     ID: 12345678 | URL: https://pubmed.ncbi.nlm.nih.gov/12345678/
# [2] [BIORXIV] Single-cell atlas of microglia in AD models
#     ID: 10.1101/2024.01.15.XXXX | URL: https://www.biorxiv.org/content/2024/01/15/XXXX
# [3] [SEMANTIC_SCHOLAR] Neuroinflammation in neurodegeneration
#     ID: abc123 | URL: https://www.nature.com/articles/XXXX
```

```bash
# 2. 관심 논문 URL을 NotebookLM에 추가
python scripts/notebooklm_wiki.py start \
    --topic "Microglia Alzheimer Research" \
    --sources "https://pubmed.ncbi.nlm.nih.gov/12345678/" \
              "https://www.biorxiv.org/content/2024/01/15/XXXX"
```

### 시나리오 2: 키워드로 검색 → 바로 LLM-wiki raw 저장 (스크립트 내 자동화)

```python
import os, sys
from pathlib import Path

scripts_dir = Path(os.environ["USERPROFILE"]) / "AppData/Local/hermes/skills/research/notebooklm-wiki/scripts"
sys.path.insert(0, str(scripts_dir))

import paper_search_multi as multi

# 키워드 검색
papers = multi.search_all_repos(
    query="microglia Alzheimer",
    max_results=5,
    lookback_days=1,
    springer_api_key=os.getenv("SPRINGER_API_KEY", ""),
    elsevier_api_key=os.getenv("ELSEVIER_API_KEY", ""),
)

print(f"검색된 논문: {len(papers)}건")

# LLM-wiki raw에 저장
wiki_raw = Path(os.environ["WIKI_PATH"]) / "raw"
for p in papers:
    # 안전한 파일명 생성 (특수문자 제거)
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in p.title)[:60]
    date_str = multi._today_iso()
    filename = f"{p.source}_{safe_title}_{date_str}.md"
    
    content = f"""---
source: {p.source}
paper_id: {p.paper_id}
title: {p.title}
url: {p.url}
published_date: {p.published_date}
authors: {', '.join(p.authors)}
---

# {p.title}

{p.abstract}

**출처**: [{p.source}]({p.url})
"""
    filepath = wiki_raw / filename
    filepath.write_text(content, encoding="utf-8")
    print(f"저장됨: {filepath}")

# 선택적으로 Slack 알림
if os.environ.get("SLACK_WEBHOOK_URL"):
    from notebooklm_wiki_sync import send_slack_message
    msg = f"📚 키워드 'microglia Alzheimer' 검색 결과 {len(papers)}건 저장 완료"
    send_slack_message(msg)
```

### 시나리오 3: .csv/.pdf/.md 파일은 이 모듈에서 사용하지 않음

```bash
# 아래는 동작하지 않음 — 키워드만 허용
python scripts/paper_search_multi.py data.csv          # 무시됨 (검색 안 함)
python scripts/paper_search_multi.py paper.pdf         # 무시됨 (검색 안 함)
python scripts/paper_search_multi.py notes.md          # 무시됨 (검색 안 함)

# 올바른 사용: 키워드만
python scripts/paper_search_multi.py "Alzheimer microglia"
python scripts/paper_search_multi.py "hiPSC microglia"
python scripts/paper_search_multi.py "neuroinflammation Alzheimer"
```

### 시나리오 4: 여러 키워드로 순차 검색

```python
import paper_search_multi as multi

queries = ["microglia Alzheimer", "hiPSC microglia", "neuroinflammation"]
all_papers = []

for q in queries:
    papers = multi.search_all_repos(q, max_results=3, lookback_days=7)
    all_papers.extend(papers)
    print(f"'{q}': {len(papers)}건")

print(f"\n총 {len(all_papers)}건 검색됨")

# 중복 제거는 이미 search_all_repos 내에서 처리됨
# 여러 쿼리 간 중복은 별도로 처리하려면:
seen = set()
unique = []
for p in all_papers:
    key = f"{p.source}:{p.paper_id}"
    if key not in seen:
        seen.add(key)
        unique.append(p)
print(f"중복 제거 후: {len(unique)}건")
```

---

# Paper Search Handler (`paper_search_handler.py`)

Searches PubMed, bioRxiv, and Semantic Scholar for a topic (via `scripts/paper_search.py`),
lists results, and (via Slack
or CLI) lets a user pick one to record in the wiki.

## Prerequisites (external, not in this repo)

- Python package `requests` (`pip install requests`). `feedparser` is no longer needed.
- Real search logic lives in `scripts/paper_search.py`; this handler converts its `Paper`
  objects into wiki/Slack-friendly dicts. arXiv is **not** used — `paper_search.py` uses
  bioRxiv instead. Springer/Elsevier require `SPRINGER_API_KEY` / `ELSEVIER_API_KEY` (skipped if absent).
- `WIKI_PATH` (default `~/wiki`). `SLACK_WEBHOOK_URL` is optional; without it, Slack alerts
  are skipped (the local CLI still works).

## CLI

```bash
python scripts/paper_search_handler.py search <query...>
python scripts/paper_search_handler.py select <index>   # 1-based, from the last search
python scripts/paper_search_handler.py status
```

- `search` runs all three engines (each wrapped in try/except; a failing engine is skipped)
  and prints/sends a numbered list. Results are persisted to `WIKI_PATH/.paper_search_state.json`
  so `select`/`status` work even in a later process.
- `select <index>` records the chosen paper: it writes a `concepts/<topic>.md` cross-reference
  and reloads prior state automatically.
- `status` shows the current in-memory (or persisted) results.

## What it writes

```
$WIKI_PATH/
├── raw/<Source>_<query>_<timestamp>.md   # search results (one file per search)
├── concepts/<topic>.md                    # appends a cross-reference per selected paper
└── .paper_search_state.json              # CLI cross-invocation state
```

Notes:
- Search-result files go to top-level `raw/` (not a topic sub-wiki).
- Concept wikilinks use the non-standard form `[[raw/<Source>:<id>]]`.
- Semantic Scholar may rate-limit or require an API key; on failure it is skipped.
- On Windows the script forces UTF-8 stdout/stderr so emoji output does not crash.

## Slack / Hermes usage

`hermes_paper_search_handler(command, args)` is the entry point the agent loop calls with
`search` / `select`. It assumes a long-running process holding state; the CLI path achieves
the same via the persisted state file.


## Slack Integration

Set `SLACK_WEBHOOK_URL` in your environment or `.env` file to enable Slack notifications:

```bash
# In your shell profile or .env file
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

### Notification Events

The script automatically sends Slack messages for:
- Research session started
- Notebook created
- Sources added (URLs and local files)
- All sources processed
- Status reports
- **Sync events** (new sources detected/written by notebooklm-wiki-sync)

### Example Slack Message (Sync)

```
📥 NotebookLM → LLM-wiki 동기화 완료

   노트북: My Research
   소스: Example Paper Title
   유형: web_page
   저장된 파일: web_page_example_paper_title_2026-08-19_15-30-00.md
```

### Example Slack Message (Status)

```
📥 **NotebookLM → LLM-wiki 동기화 완료**

   새로 저장된 소스: 2개
   대상 노트북: 1개

   저장된 파일:
   - web_page_paper_a_2026-08-19_15-30-00.md
   - pdf_report_b_2026-08-19_15-30-15.md
```

## File Structure (written by all scripts)

```
$WIKI_PATH/
├── raw/                          # Saved NotebookLM sources + search results
│   ├── <Source>_<query>_<timestamp>.md   # search results (one file per search)
│   ├── <type>_<title>_<timestamp>.md     # synced NotebookLM sources
│   └── assets/                   # podcast.mp3, quiz.md (fixed filenames)
├── concepts/                     # Cross-reference pages (one per topic)
│   └── <topic>.md                # appends links to selected papers
├── .paper_search_state.json      # CLI cross-invocation state (paper search)
└── .notebooklm_sync_state.json   # Sync state: list of synced source IDs
```

## Troubleshooting

### Sync script shows "조회 가능한 노트북이 없습니다"
- NotebookLM 인증이 만료됨 → `notebooklm login` 실행 후 재시도
- 프로필이 여러 개라면 `NOTEBOOKLM_PROFILE` 환경 변수 확인

### Dry-run에서만 결과가 나오고 실제 저장 안 됨
- `sync` 명령에 `--dry-run` 플래그가 붙었는지 확인
- 소스 상태가 `processing` 또는 `error`이면 건너뜀 → 상태가 `ready`인지 확인

### Slack 알림이 오지 않음
- `SLACK_WEBHOOK_URL` 환경 변수가 설정되어 있는지 확인
- Webhook URL이 유효한지 `curl`로 테스트:  
  `curl -X POST -H "Content-type: application/json" --data '{"text":"test"}' $SLACK_WEBHOOK_URL`

## Related Skills

- `llm-wiki` — Core knowledge base management
- `obsidian` — Note viewing and editing
- `arxiv` — Academic paper discovery
