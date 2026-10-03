# AGENTS.md — research_new

Daily paper bot: 5-source search → Local LLM summarization → Slack. No git, no package manager, no test suite. `SKILL.md` is the authoritative spec.

## Run

```bash
# Manual (must use hermes venv — not system python):
"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -u scripts/research_pipeline.py
"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -u scripts/research_pipeline.py "New Topic" 1

# Individual modules:
"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -u scripts/paper_search.py 1
"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -u scripts/local_llm_summarize.py "Topic" 1
```

- Cron `a408cad4c3f1` — `0 5 * * *` KST, `workdir: research_new`, `no_agent` mode (only stdout runs). Registered via `hermes cron`.
- `scripts/run_pipeline.py` and `scripts/run_pipeline.bat` are wrappers that `chdir` to `scripts/` and hardcode the venv path — prefer calling `research_pipeline.py` directly. `run_pipeline.bat:9-16` additionally loads `SLACK_BOT_TOKEN` from `%USERPROFILE%\AppData\Local\hermes\.env`.
- Log: `scripts/research_pipeline.log` (append-only `FileHandler`, no rotation — `research_pipeline.py:46`).

## Config — `.env` is source of truth

| Var | Meaning | Pitfall |
|-----|---------|---------|
| `RESEARCH_TOPIC` | `;` or `,` separated keywords (`paper_search.py:644`) | `&` in terms (e.g. `autism&macrophage`) is only sanitized for Springer (`paper_search.py:372`); Elsevier/bioRxiv break |
| `RESEARCH_MAX_RESULTS` | **per-source per-keyword candidate pool**, not final count (25 → up to 625 candidates before dedup) | Large values inflate search time only; selection is capped separately |
| `RESEARCH_MAX_PAPERS_PER_KEYWORD` | **final picks per keyword** (default 5), ranked by journal impact factor (`_IMPACT_FACTOR` + citation bonus) | Unfilled keyword quotas refill from leftovers by IF |
| `RESEARCH_MAX_TOTAL_PAPERS` | safety-net absolute cap after selection (default 30) | Second line of defense; time budget is the primary guard |
| `RESEARCH_LOOKBACK_DAYS` | date filter — only PubMed/bioRxiv honor it | SS/Springer/Elsevier have no client-side date filter |
| `LOCAL_LLM_URL` / `VISION_LLM_URL` | GLM-5.2 / Qwen2.5-VL | `LLM_MODEL=""` means auto-select via `GET /v1/models` |
| `SPRINGER_API_KEY` / `ELSEVIER_API_KEY` | query-param auth | Missing → source silently skipped; Elsevier 401/403 → key/entitlement 문제 (선택 `ELSEVIER_INST_TOKEN`) |
| `SLACK_BOT_TOKEN` / `SLACK_CHANNEL` | `SLACK_CHANNEL` is an ID (`C0BS...`), not `#name` (`SKILL.md:7.9`) | Token captured at import time (`slack_research_notifier.py:32`) |

`.env.example` currently contains live secrets — do not commit. No `.gitignore` exists yet; add `.env`, `__pycache__/`, `*.log` if initializing git.

## Architecture

```
research_pipeline.py:84  search_all()          — fan-out to 5 sources (no per-source try/except; one throw kills all)
                         → dedup by normalized title (paper_search.py:673, list scan)
                         → sequential loop summarize_paper() (research_pipeline.py:108)
                         → build_daily_message() + send_to_slack() (chunked at 3000 chars)
```

- `paper_search.py` — PubMed (`esearch`+`esummary`+`efetch` XML, `pdat`), bioRxiv (date-range + client OR), Semantic Scholar, Springer (`openaccess/json`, 404 시 평문 쿼리 재시도), Elsevier (**ScienceDirect Search API V2** `/content/search/sciencedirect`, STANDARD view + `X-ELS-APIKey` 헤더; 초록 없으면 META→Crossref→OpenAlex 보강). 진화형 참조: `../notebooklm-wiki/scripts/paper_search.py`.
- `local_llm_summarize.py` — `summarize_abstract(mode=)` → `LOCAL_LLM_URL` (abstract/fulltext 두 모드; Vision 경로 제거됨). PDF extraction via `pymupdf` (installed in hermes venv).
- `slack_research_notifier.py` — groups by `source`, splits at `MAX_MESSAGE_CHARS=3000`.

## Gotchas — verified from code

- **No global paper cap or time budget.** Sequential LLM loop with `timeout=2400s × 3 retries` (`local_llm_summarize.py:260,321`) → 88 papers ≈ 4–7 h (see `research_pipeline.log` tail ending at 43/88 on 2026-08-21). Cron 3 h budget will always fire if `RESEARCH_MAX_RESULTS` is large. Keep `RESEARCH_MAX_RESULTS=3` per `SKILL.md:7.7`.
- **Wrapper self-spawn bug (historical).** `run_pipeline.py:26` does `subprocess.call([VENV_PYTHON, os.path.join(SCRIPT_DIR, "research_pipeline.py")])`. A copy of this wrapper placed as `hermes/scripts/research_pipeline.py` spawns itself infinitely — ensure cron points at `skills/research/research_new/scripts/research_pipeline.py`.
- **Springer retry missing `for-else`** — `paper_search.py:386` has no `else: return []` unlike `search_semantic_scholar:309` / `search_elsevier:542`; three consecutive 429s leave `data` undefined → `NameError` at `data.get("records")` and `search_all` has no per-source guard so all other sources' results are lost.
- **bioRxiv pagination is single-page.** `page_size = max_results * 20` (`paper_search.py:211`), `cursor += page_size` (`paper_search.py:261`), `cursor < 200` (`paper_search.py:213`) → with `max_results=25`, page_size=500 so `cursor` goes 0→500 and the loop exits after one fetch. `base_url:204` is dead code.
- **bioRxiv OR is word-level.** `re.split(r"\s+", query_lower)` (`paper_search.py:202`) → `"Cancer Immunotherapy"` matches any paper containing `cancer` OR `immunotherapy`.
- **Vision path removed.** `summarize_image()`/`find_graphical_abstract_url()` are deleted; Graphical Abstract output is gone. Fulltext mode (bioRxiv/SS PDF → Head+Tail 발췌 + 전체 Figure 캡션) is preferred, abstract mode falls back with `(추론)` inference markers allowed.
- **PDF fallback never fires.** `summarize_paper:387` checks `pdf_url.endswith(".pdf")` — PubMed HTML URLs and bioRxiv `raw` (no `pdf_url` key) always fail → `"초록 정보를 가져올 수 없습니다."`.
- **Elsevier `for-else` is dead code** — `ConnectionError → return` inside the loop (`paper_search.py:533`) prevents reaching the `else` clause; inconsistent with SS/Springer.
- **Windows paths:** use `C:/Users/...` native (`SKILL.md:7.8`); MSYS `/c/...` is not understood by the hermes venv Python.
- **Stale labels:** `research_pipeline.py:97` logs `PubMed+arXiv+SS` but now searches 5 sources; `research_pipeline.py:58` globals `TOPIC`/`LOOKBACK_DAYS` are mutated from `sys.argv` at import time — breaks reuse/tests.
