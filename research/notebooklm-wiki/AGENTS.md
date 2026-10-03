# AGENTS.md — notebooklm-wiki skill

This repo is a **Hermes Agent skill**, not a standalone app. It contains two scripts
that wrap external services and push results into an LLM-wiki. `SKILL.md` is the skill
metadata + user-facing docs; treat `scripts/*.py` as the source of truth when they disagree.

## Prerequisites (external, not in this repo)
- `notebooklm` CLI must be installed, on PATH, and authenticated separately.
- `paper_search_handler.py` needs the third-party `requests` package (`pip install requests`). `feedparser` is no longer required — search logic moved to `paper_search.py`.
- `WIKI_PATH` env var sets the wiki root (default `~/wiki`). `NOTEBOOKLM_PROFILE` is read by docs but unused in code. Slack alerts need `SLACK_WEBHOOK_URL`.

## Scripts

### `scripts/notebooklm_wiki.py` — NotebookLM wrapper
```bash
python scripts/notebooklm_wiki.py <command> --...
```
Commands (all implemented): `start`, `podcast`, `quiz`, `status`, `download-all`.
- `start` requires `--topic` **and** `--sources` (1+ URLs/paths).
- Routing uses argparse `dest="command"` — new subcommands need a single edit in the `__main__` block.
- `flashcards`, `source add-research`, `research wait`, `notebooklm auth refresh` appear in `SKILL.md` but are **NOT implemented** — ignore them.

Gotchas:
- `generate_podcast` always writes to `WIKI_PATH/raw/assets/podcast.mp3`, `generate_quiz` to `.../quiz.md` — fixed filenames, repeat runs **overwrite**.
- `save_to_wiki_raw` writes straight to `WIKI_PATH/raw/`, bypassing LLM-wiki's topic-subwiki layout (`HUB/topics/<slug>/`); it skips (warns) if the target file already exists.
- Assumes `notebooklm` subcommands accept `--json` and `-n <notebook-id>`; verify against the installed CLI.
- Source-processing failures are swallowed (`wait_for_sources` skips on error); a "success" run can still be missing sources.
- Auth is **cookie-based (Google)**. `notebooklm auth refresh` re-validates stored cookies; `run_notebooklm_command` auto-runs it and retries once when a command fails with an auth-looking error (so a mid-run cookie drop self-heals). If auth keeps dropping, run `notebooklm auth check` / `notebooklm auth refresh` manually first.

### `scripts/paper_search_handler.py` — paper search (delegates to `paper_search.py`)
Search logic was extracted into `scripts/paper_search.py` (dataclass `Paper`, date-window
filtering, dedup, sources: PubMed / bioRxiv / Semantic Scholar / Springer / Elsevier).
The handler calls `paper_search.search_all()` and converts results to dicts for Slack/wiki.
**arXiv is gone** — `paper_search.py` uses bioRxiv instead. Springer/Elsevier need API keys
(`SPRINGER_API_KEY` / `ELSEVIER_API_KEY`); they're skipped when absent.
```bash
python scripts/paper_search_handler.py search <query...>
python scripts/paper_search_handler.py select <index>   # 1-based, from last search
python scripts/paper_search_handler.py status
```
- Designed for a long-running Hermes/Slack loop, but also runnable from CLI.
- **Cross-invocation state**: search results live in an in-memory singleton that did NOT survive separate CLI calls. Fixed by persisting to `WIKI_PATH/.paper_search_state.json`; `select`/`status` now reload it. Run `search` then `select` in any order of invocations.
- `send_slack_message` assumed Slack webhooks return JSON; they return plain text `"ok"`, so every send was misreported as failed. Fixed to check the HTTP status + body.
- On Windows the console is `cp949`; the script forces `sys.stdout/stderr` to UTF-8 so emoji prints don't raise `UnicodeEncodeError`.
- Each search engine is wrapped in try/except; a failing source is skipped, not fatal.
- `save_to_llmwiki` writes to `WIKI_PATH/raw/` and `update_concept_page` writes to `WIKI_PATH/concepts/` (top-level, not topic sub-wikis). The concept wikilinks use a non-standard `[[raw/<Source>:<id>]]` form.

## Structure
```
SKILL.md                          # frontmatter + docs (may drift from code)
scripts/notebooklm_wiki.py            # NotebookLM → wiki wrapper
scripts/paper_search.py            # search engine (PubMed/bioRxiv/SS/Springer/Elsevier)
scripts/paper_search_handler.py   # wraps it → Slack/wiki (arXiv replaced by bioRxiv)
scripts/notebooklm_wiki_sync.py   # NotebookLM→wiki watcher/daemon (sync/daemon/status/reset)
```
No tests, build, lint, or package manifest exist here — keep changes to the scripts + docs.
