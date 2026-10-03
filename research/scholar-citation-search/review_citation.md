# Code Review: scholar-citation-search Implementation vs plans_citation.md v1.3.0

**Review Date**: 2026-09-05 (Updated)  
**Reviewer**: Manual review (remote_codex timeout)  
**Files Reviewed**: 
- `src/citation_pipeline.py` (main orchestrator)
- `src/batch_pipeline.py` (NEW - batch processing with resume)
- `src/paper_acquisition.py` (3-tier body acquisition)
- `src/scite_client.py` (scite MCP client)
- `src/text_extraction.py` (PDF extraction + LLM filter)
- `src/academic_mcp_direct.py` (academic-mcp subprocess wrapper)

---

## Executive Summary

**Overall Verdict**: **PARTIAL IMPLEMENTATION (~65% spec compliance)** — Significant progress since last review. New `batch_pipeline.py` implements v1.3.0 batch/resume requirements. `citation_pipeline.py` now has SHA256 pre-scan cache, attachments/ raw PDF handling, unique filepath logic, and backlink support. However, critical gaps remain in canonicalization (Step ①), Scholar browser_exec (Step ②), LLM filter completeness (Step ⑤), and scite evidence fields (Step ⑥).

---

## File-by-File Analysis

### 1. citation_pipeline.py — Main Pipeline Orchestrator

#### ✅ Implemented Correctly (v1.3.0 improvements)
- Overall 6-step pipeline structure (enrich → acquire → extract/filter → verify → save)
- OpenAlex enrichment via DOI/title lookup
- 3-tier body acquisition delegation to `paper_acquisition.py`
- scite verification via `SciteClient`
- **SHA256 pre-scan cache** (`build_sha256_set`, `check_existing_sha256_cached`, `invalidate_sha256_cache`) — Gap b addressed
- **Unique filepath handling** with SHA256 suffix (`get_unique_filepath`) — Gap d addressed
- **Raw PDF copy to `attachments/` directory** — v1.3.0 raw file management
- **Backlink support** (`source_doi`, `cites: [[...]]`) — v1.3.0 citing paper backlinks
- **Obsidian Properties v2 compatible frontmatter** (authors as array, no extra quotes)
- Vault validation (exists + writable)

#### ❌ Critical Gaps

| # | Issue | Location | Spec Requirement | Fix Needed |
|---|-------|----------|------------------|------------|
| 1 | **No canonicalization logic** | Lines 380-385 (`run_pipeline`) | Step ①: DOI normalization, OpenAlex ID priority, version-of-record, SHA256 dedup | Add `canonicalize_paper()` function before enrichment |
| 2 | **No Scholar browser_exec** | Lines 85-120 (`collect_scholar_cited_by`) | Step ②: Actual browser_exec, captcha detection, exponential backoff | Implement browser_exec or document as known limitation |
| 3 | **Missing `referenced_works`** | Lines 122-160 (`enrich_paper`) | Step ③: OpenAlex `referenced_works` for references | Extract `referenced_works` from OpenAlex response |
| 4 | **LLM filter incomplete** | Lines 195-215 (`extract_and_filter`) | Step ⑤: RQ 3-class, method similarity, needs_human_review queue | Enhance `text_extraction.py` filter output |
| 5 | **scite missing fields** | Lines 230-290 (`_verify_scite_async`) | Step ⑥: `evidence_excerpt`, `source_version`, `retrieved_at` | Add these fields to `SciteVerification` and populate |
| 6 | **Hardcoded Windows paths** | Lines 22-25 | Spec: No absolute paths | Use `Path.home()` / env vars consistently |
| 7 | **No `evidence_excerpt` in frontmatter** | Lines 300-330 | Spec: frontmatter must include `evidence_excerpt` | Add to `build_obsidian_frontmatter` |
| 8 | **No `retrieved_at` in scite output** | Line 260 | Spec: ISO8601 retrieval timestamp | Add to `SciteVerification` |

#### 🔧 Specific Code Fixes

**Fix 1: Add canonicalization function (after line 175)**
```python
async def canonicalize_paper(paper: CanonicalPaper) -> CanonicalPaper:
    """Step ①: 정준화/중복 제거"""
    # DOI 정규화
    if paper.doi:
        paper.doi = paper.doi.lower().strip().replace("https://doi.org/", "")
    # OpenAlex ID 우선순위 적용 등은 enrich_paper에서 처리
    return paper
```

**Fix 2: Add `referenced_works` to enrich_paper (line 155)**
```python
# OpenAlex referenced_works 추출
ref_works = data.get("referenced_works", [])
paper.referenced_works = [w.replace("https://openalex.org/", "") for w in ref_works]
```

**Fix 3: Add scite evidence fields (line 260)**
```python
result.evidence_excerpt = paper_data.get("evidence_excerpt", "")
result.source_version = paper_data.get("version", "v1")
result.retrieved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
```

**Fix 4: Add `evidence_excerpt` to frontmatter (line 315)**
```python
if verification.evidence_excerpt:
    lines.append(f'evidence_excerpt: "{_esc(verification.evidence_excerpt[:500])}"')
if verification.retrieved_at:
    lines.append(f'retrieved_at: "{verification.retrieved_at}"')
```

---

### 2. batch_pipeline.py — NEW: Batch Processing with Resume (v1.3.0)

#### ✅ Implemented Correctly
- **Gap g: `batch_progress.json` for resume support** — atomic write with `.tmp` replace
- **Gap a: Rate limit throttle** (1.0s between scite/OpenAlex calls)
- **Gap b reuse: SHA256 pre-scan cache** from citation_pipeline
- **Gap d reuse: Unique filepath logic** via `get_unique_filepath`
- **Citing papers individual save** with backlinks (`source_doi`, `cites: [[...]]`)
- **Resume logic**: skips completed DOIs from progress file
- Progress file per source DOI (SHA1 hash for filename)

#### ❌ Gaps

| # | Issue | Location | Spec Requirement | Fix Needed |
|---|-------|----------|------------------|------------|
| 1 | **No canonicalization for citing papers** | Line 140 | Step ①: Each citing paper needs canonicalization | Call `canonicalize_paper()` before enrich |
| 2 | **No `referenced_works` for citing papers** | Line 150 | Step ③: References for citing papers | Add to enrich_paper output |
| 3 | **LLM filter incomplete for citing papers** | Line 165 | Step ⑤: Same gaps as main pipeline | Fix in text_extraction.py |
| 4 | **scite missing evidence fields for citing papers** | Line 175 | Step ⑥: Same gaps as main pipeline | Fix in scite_client.py |
| 5 | **No vault capacity warning** | N/A | v1.3.0: PDF 4.4MB × 50 ≈ 220MB warning | Add check before batch |
| 6 | **No `filter_verdict`/`rq_class` in output** | Line 180 | Spec: JSON output schema | Extend return dict |

#### 🔧 Specific Code Fixes

**Fix 1: Add vault capacity check (before line 200)**
```python
def check_vault_capacity(vault_path: Path, estimated_pdfs: int, avg_mb: float = 4.4) -> None:
    """v1.3.0: vault 용량 경고"""
    import shutil
    free_gb = shutil.disk_usage(vault_path).free / (1024**3)
    needed_gb = (estimated_pdfs * avg_mb) / 1024
    if free_gb < needed_gb * 1.5:
        print(f"⚠️  용량 경고: 여유 {free_gb:.1f}GB, 필요 ~{needed_gb:.1f}GB")
```

**Fix 2: Add canonicalization call (line 140)**
```python
# ① CanonicalPaper 생성 후 정준화
paper = CanonicalPaper(...)
paper = await canonicalize_paper(paper)  # NEW
```

---

### 3. paper_acquisition.py — 3-Tier Body Acquisition

#### ✅ Implemented Correctly
- Tier1: OA direct download with PDF magic byte validation
- Tier2: web_extract landing page PDF link discovery
- Tier3: academic-mcp via `AcademicMcpDirect` subprocess
- Fallback to `abstract_only`
- SHA256 computation on download
- Tier attempt tracking and result logging

#### ❌ Gaps

| # | Issue | Location | Spec Requirement | Fix Needed |
|---|-------|----------|------------------|------------|
| 1 | **Tier2 uses `hermes_tools.web_extract`** | Line 105 | Spec: `web_extract` tool | Verify `hermes_tools` availability; add fallback |
| 2 | **No retry/backoff on HTTP** | Lines 30-70 | Spec: Exponential backoff 3x | Add retry logic to `fetch_pdf_direct` |
| 3 | **Tier3 uses subprocess not MCP** | Lines 140-170 | Spec: MCP normal path (`streamable_http_client`) | Document as design decision for isolation |
| 4 | **No landing_url auto-discovery from DOI** | Line 200 | Tier2 needs landing URL | Auto-construct from DOI |

#### 🔧 Specific Code Fixes

**Fix 1: Add retry to fetch_pdf_direct (line 30)**
```python
async def fetch_pdf_direct(..., max_retries: int = 3, base_delay: float = 2.0):
    for attempt in range(max_retries):
        try:
            # ... existing code
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if attempt == max_retries - 1:
                return None, None, f"재시도 {max_retries}회 실패: {e}"
            await asyncio.sleep(base_delay * (2 ** attempt))
```

**Fix 2: Add landing_url auto-discovery (line 200)**
```python
# DOI가 있으면 landing_url 자동 구성
if not landing_url and paper.get("doi"):
    landing_url = f"https://doi.org/{paper['doi']}"
```

---

### 4. scite_client.py — scite MCP Client

#### ✅ Implemented Correctly
- MCP streamable HTTP client pattern
- Token loading from `~/.hermes/.env` with encoding fallbacks
- Core tools: `paper_by_doi`, `paper_by_title`, `search`, `citing_papers`, `read_fulltext`, `bibliography`, `tally`
- Result parsing via `parse_mcp_result`

#### ❌ Gaps

| # | Issue | Location | Spec Requirement | Fix Needed |
|---|-------|----------|------------------|------------|
| 1 | **Missing `editorialNotices` field** | Line 85 | Spec: `editorialNotices` for retraction check | Add to `paper_by_doi` return |
| 2 | **No `evidence_excerpt` extraction** | N/A | Spec: `evidence_excerpt` from citations | Add method to extract from `citations[]` |
| 3 | **No `source_version` field** | N/A | Spec: DOI version tracking | Add if available in response |
| 4 | **No `retrieved_at` timestamp** | N/A | Spec: ISO8601 retrieval time | Add in calling code (citation_pipeline.py) |
| 5 | **No `citation_graph` wrapper** | Line 95 | Spec: citation_graph for cross-verification | Already exists as `citing_papers` |

#### 🔧 Specific Code Fixes

**Fix 1: Enhance paper_by_doi to return editorialNotices (line 85)**
```python
async def paper_by_doi(self, doi: str) -> dict | None:
    data = await self._call("search_literature", dois=[doi], limit=1)
    if data and data.get("hits"):
        hit = data["hits"][0]
        # editorialNotices 정규화
        if "editorialNotices" in hit:
            hit["editorial_notices"] = hit["editorialNotices"]
        return hit
    return None
```

**Fix 2: Add evidence extraction method**
```python
async def get_evidence_snippets(self, doi: str, limit: int = 3) -> list[dict]:
    """citations[]에서 evidence snippet 추출"""
    paper = await self.paper_by_doi(doi)
    if not paper or not paper.get("citations"):
        return []
    return [
        {
            "context": c.get("context", ""),
            "type": c.get("type", ""),
            "section": c.get("section", ""),
            "source_doi": c.get("sourceDoi", ""),
        }
        for c in paper["citations"][:limit]
        if c.get("context")
    ]
```

---

### 5. text_extraction.py — PDF Extraction + LLM Filter

#### ✅ Implemented Correctly
- PyMuPDF primary, pdfplumber fallback
- Section splitting with regex headers (abstract, intro, method, result, discussion, conclusion)
- Priority section ordering
- LLM similarity filter with OpenAI-compatible API
- Keyword fallback when no API key
- Chunking at 500 words
- SHA256 per chunk
- Score threshold filtering

#### ❌ Gaps

| # | Issue | Location | Spec Requirement | Fix Needed |
|---|-------|----------|------------------|------------|
| 1 | **No RQ 3-class classification** | Lines 180-250 | Spec: `same/related/unrelated` | Current returns only float score |
| 2 | **No method similarity (Jaccard/LLM)** | N/A | Spec: method similarity high/medium/low | Add separate method |
| 3 | **No `needs_human_review` queue** | N/A | Spec: related bottom 50% + low confidence → queue | Add queue logic |
| 4 | **No `filter_reason`, `rq_class`, `method_similarity`, `tfidf_score`, `confidence` fields** | Line 240 | Spec: All decisions preserved in JSON | Extend return dict |
| 5 | **TF-IDF cosine not implemented** | N/A | Spec: TF-IDF ≥0.35 as auxiliary | Add sklearn TF-IDF |
| 6 | **LLM prompt doesn't match spec** | Lines 130-150 | Spec: 3-question prompt format | Update prompt template |

#### 🔧 Specific Code Fixes

**Fix 1: Add RQ classification method (new function)**
```python
def classify_rq_similarity(
    candidate_text: str,
    original_rq: str,
    api_key: str | None = None,
    model: str = "gpt-4o-mini",
) -> dict:
    """RQ 3-class 분류: same/related/unrelated + confidence"""
    prompt = f"""원본 RQ: "{original_rq}"
후보 논문 abstract+intro: "{candidate_text[:4000]}"
Q1: 후보 논문이 원본과 동일한 연구 질문을 다루는가? (same/related/unrelated)
Q2: 방법론이 유사한가? (high/medium/low)
Q3: 이 논문을 "비슷한 전개"로 볼 수 있는가? (yes/no + 1줄 근거)
JSON으로만 응답: {{"rq_class": "...", "method_similarity": "...", "verdict": "...", "reason": "...", "confidence": "high|medium|low"}}"""
    # LLM 호출 후 파싱
    ...
```

**Fix 2: Update filter_by_rq to use classification (line 200)**
```python
# 각 청크에 대해 분류 수행
classification = classify_rq_similarity(chunk, research_question, api_key=api_key, model=model)
rq_class = classification["rq_class"]
method_sim = classification["method_similarity"]
verdict = classification["verdict"]
confidence = classification["confidence"]
reason = classification["reason"]

# TF-IDF 보조 점수
tfidf_score = compute_tfidf_similarity(chunk, research_question)

# 통과 조건: same + related(상위 50%) + method high/medium
passes = (rq_class == "same" or 
          (rq_class == "related" and score >= threshold) and 
          method_sim in ("high", "medium"))

# human_review 큐: related 하위 50% 또는 confidence low
needs_review = (rq_class == "related" and score < threshold) or confidence == "low"

scored.append({
    "section": sec_name,
    "text": chunk,
    "score": round(score, 3),
    "sha256": chunk_hash,
    "source_file": source_file,
    "rq_class": rq_class,
    "method_similarity": method_sim,
    "tfidf_score": round(tfidf_score, 3),
    "confidence": confidence,
    "filter_reason": reason,
    "verdict": "kept" if passes else ("needs_human_review" if needs_review else "filtered_out"),
})
```

**Fix 3: Add TF-IDF computation**
```python
from sklearn.feature_extraction.text import TfidfVectorizer

def compute_tfidf_similarity(text1: str, text2: str) -> float:
    try:
        vec = TfidfVectorizer(stop_words='english', max_features=1000)
        tfidf = vec.fit_transform([text1, text2])
        return float((tfidf[0] @ tfidf[1].T).toarray()[0,0])
    except Exception:
        return 0.0
```

---

### 6. academic_mcp_direct.py — academic-mcp Subprocess Wrapper

#### ✅ Implemented Correctly
- Subprocess isolation for MCP version conflict
- JSON-RPC over stdin/stdout
- Worker script with search/download/read/metadata/list_sources
- Async context manager pattern
- Source filtering (disabled paid sources)

#### ❌ Gaps

| # | Issue | Location | Spec Requirement | Fix Needed |
|---|-------|----------|------------------|------------|
| 1 | **Uses subprocess not MCP protocol** | Lines 200-250 | Spec: "MCP 정상 경로 streamable_http_client + ClientSession.call_tool" | Document as design decision for isolation |
| 2 | **No timeout on worker startup** | Line 220 | Spec: Network timeout handling | Add startup timeout |
| 3 | **Worker script assumes `academic_mcp.__main__`** | Line 55 | May break if module structure changes | Add import error handling |

#### 🔧 Specific Code Fixes

**Fix 1: Add startup timeout (line 220)**
```python
async def __aenter__(self):
    # ... existing code
    try:
        await asyncio.wait_for(self._wait_for_ready(), timeout=10.0)
    except asyncio.TimeoutError:
        self._process.terminate()
        raise RuntimeError("Worker startup timeout")
```

**Fix 2: Document design decision (add to class docstring)**
```python
"""
Note: This uses subprocess + JSON-RPC instead of direct MCP protocol
to isolate academic-mcp (MCP 1.x) from Hermes (MCP 2.x).
This is a deliberate design choice, not a spec violation.
"""
```

---

## Cross-Cutting Issues

### Hardcoded Paths Audit

| File | Line | Path | Status |
|------|------|------|--------|
| citation_pipeline.py | 22 | `Path.home() / "AppData" / "Local" / "Temp" / "academic-mcp-venv" / "Scripts" / "python.exe"` | ⚠️ Windows-specific but uses `Path.home()` — acceptable |
| citation_pipeline.py | 23 | `Path.home() / "AppData" / "Local" / "Temp" / "academic-mcp-downloads"` | ⚠️ Same — acceptable |
| batch_pipeline.py | 22 | Same DOWNLOAD_DIR | ⚠️ Same — acceptable |
| academic_mcp_direct.py | 27-30 | Candidate paths with `Path.home()` | ✅ Uses `Path.home()` |
| paper_acquisition.py | N/A | Uses passed `save_dir` | ✅ No hardcoded |

**Verdict**: No absolute hardcoded paths like `C:\Users\user\...` — all use `Path.home()` or env vars. **PASS**.

### Output Schema Compliance

| Spec Field | citation_pipeline.py | batch_pipeline.py | Status |
|------------|---------------------|-------------------|--------|
| `input_paper.openalex_id` | ✅ in `CanonicalPaper` | N/A | PASS |
| `citing_papers[].filter_verdict` | ❌ missing | ❌ missing | FAIL |
| `citing_papers[].rq_class` | ❌ missing | ❌ missing | FAIL |
| `citing_papers[].method_similarity` | ❌ missing | ❌ missing | FAIL |
| `citing_papers[].tfidf_score` | ❌ missing | ❌ missing | FAIL |
| `citing_papers[].scite.evidence_excerpt` | ❌ missing | ❌ missing | FAIL |
| `citing_papers[].scite.source_version` | ❌ missing | ❌ missing | FAIL |
| `citing_papers[].scite.retrieved_at` | ❌ missing | ❌ missing | FAIL |
| `stats.deduped` | ❌ missing | ❌ missing | FAIL |
| `stats.needs_review` | ❌ missing | ❌ missing | FAIL |

---

## Test Execution Notes

### Manual Test Attempts

**Test 1: citation_pipeline.py --help**
```bash
python src/citation_pipeline.py --help
```
- Works, shows all arguments

**Test 2: batch_pipeline.py --help**
```bash
python src/batch_pipeline.py --help
```
- Works, shows all arguments including `--resume`

**Test 3: scite_client.py standalone**
```bash
python src/scite_client.py
```
- Requires `SCITE_ACCESS_TOKEN` in `~/.hermes/.env`
- Without token: "SCITE_ACCESS_TOKEN이 없습니다"

**Test 4: paper_acquisition.py standalone**
```bash
python src/paper_acquisition.py
```
- Requires academic-mcp venv at `~/AppData/Local/Temp/academic-mcp-venv`
- Without venv: "academic-mcp 가상환경 Python을 찾을 수 없습니다"

**Test 5: text_extraction.py**
```bash
python src/text_extraction.py --input test.pdf --rq "test question"
```
- Requires PyMuPDF or pdfplumber
- Requires `LLM_API_KEY` for full functionality (falls back to keyword)

---

## Priority Fix List (Updated)

### P0 (Blocking - Must Fix Before Use)
1. **Add canonicalization logic** (citation_pipeline.py + batch_pipeline.py) — Step ① not implemented
2. **Add Scholar browser_exec or document limitation** (citation_pipeline.py) — Step ② uses OpenAlex fallback only
3. **Add `referenced_works` to OpenAlex enrichment** (citation_pipeline.py) — Step ③ incomplete
4. **Implement RQ 3-class + method similarity in LLM filter** (text_extraction.py) — Step ⑤ incomplete
5. **Add scite evidence_excerpt, source_version, retrieved_at** (scite_client.py + citation_pipeline.py) — Step ⑥ incomplete
6. **Add `evidence_excerpt` and `retrieved_at` to frontmatter** (citation_pipeline.py) — v1.3.0 requirement

### P1 (Important - Should Fix)
7. **Add retry/backoff to HTTP calls** (paper_acquisition.py, citation_pipeline.py)
8. **Add TF-IDF cosine auxiliary score** (text_extraction.py)
9. **Add `needs_human_review` queue logic** (text_extraction.py + citation_pipeline.py)
10. **Extend output JSON schema to match spec** (citation_pipeline.py + batch_pipeline.py)
11. **Add vault capacity warning** (batch_pipeline.py)

### P2 (Nice to Have)
12. **Document academic-mcp subprocess design decision** (academic_mcp_direct.py)
13. **Add startup timeout to AcademicMcpDirect** (academic_mcp_direct.py)
14. **Add landing_url auto-discovery from DOI** (paper_acquisition.py)

---

## Verification Checklist for Next Iteration

- [ ] Run `python src/citation_pipeline.py --doi "10.18653/v1/N19-1423" --rq "test" --vault "test_vault"` end-to-end
- [ ] Run `python src/batch_pipeline.py --doi "10.18653/v1/N19-1423" --rq "test" --vault "test_vault" --max-citing 5` end-to-end
- [ ] Verify `attachments/` and `Inbox/` structure created correctly
- [ ] Verify `batch_progress.json` written and readable (resume works)
- [ ] Verify citing papers saved as individual .md files in `Inbox/{year}/citing/`
- [ ] Verify SHA256 cache works (second run skips duplicates)
- [ ] Verify frontmatter includes all v1.3.0 fields (`evidence_excerpt`, `retrieved_at`, `raw_pdf`, `source_doi`, `cites`)
- [ ] Verify `evidence_excerpt`, `retrieved_at` in scite output
- [ ] Verify LLM filter returns `rq_class`, `method_similarity`, `needs_human_review`
- [ ] Verify `referenced_works` in OpenAlex enrichment output

---

## Appendix: Spec vs Implementation Mapping (Updated)

| Spec Step | plans_citation.md | citation_pipeline.py | batch_pipeline.py | Status |
|-----------|-------------------|---------------------|-------------------|--------|
| ① Input + Canonicalization | DOI norm, OpenAlex ID, version-of-record, SHA256 | ❌ Missing canonicalize function | ❌ Missing | 20% |
| ② Scholar Cited-by | browser_exec, captcha, backoff, SerpApi fallback | ⚠️ OpenAlex fallback only | N/A | 40% |
| ③ OpenAlex Enrichment | DOI, abstract, OA URL, referenced_works | ⚠️ Missing referenced_works | ⚠️ Missing | 70% |
| ④ 3-tier Body | Tier1 OA, Tier2 web_extract, Tier3 MCP | ✅ Implemented via paper_acquisition | ✅ Reuses | 90% |
| ⑤ Text + LLM Filter | RQ 3-class, method sim, TF-IDF, human_review | ⚠️ Score only, no classification | ⚠️ Same | 40% |
| ⑥ scite + Obsidian | search_literature, citation_graph, editorialNotices, evidence_excerpt, retrieved_at, v1.3.0 Obsidian | ⚠️ Missing evidence fields | ⚠️ Same | 60% |
| **v1.3.0 Batch/Resume** | batch_progress.json, throttle, citing individual save | N/A | ✅ Implemented | 95% |

**Overall: ~65% spec compliance** (improved from ~55%)

---

## 재검증 (2026-09-05 21시대 수정분 — 실행 검증 포함)

### 변경된 파일 (mtime 기준)
- `src/citation_pipeline.py` — modified 20:57 (전면 재작성 수준)
- `src/scite_client.py` — modified 20:53 (`citing_papers`→`citation_graph` 개명, `editorial_notices` 추가)
- `src/batch_pipeline.py` (20:07), `paper_acquisition.py`, `text_extraction.py`, `academic_mcp_direct.py` — 변경 없음

### 실행 검증 결과
- `py_compile`: citation_pipeline.py OK, scite_client.py OK (문법 오류 없음)
- `import batch_pipeline` → **ImportError: cannot import name 'enrich_paper' from 'citation_pipeline'** (실행 불가 확인)
- 속성 점검: `enrich_paper, acquire_body, extract_and_filter, collect_scholar_cited_by, fetch_openalex_by_doi, load_env_key` 전부 `citation_pipeline`에 없음 / `argparse` import 없음 / `_vault_sha256_cache` 정의 없음
- remote_codex 재시도(1문장 질문) → 다시 timeout. 본 검증은 로컬 실행 결과 기반.

### 결론: 제대로 수정되지 않음 — 리그레션 발생
이번 수정은 컴파일은 통과하지만 **런타임에 즉시 깨진다**. `batch_pipeline.py`가 통째로 import 불가하므로 배치 파이프라인 전체가 동작하지 않는다.

| # | 문제 | 위치 | 증상 | 수정안 |
|---|------|------|------|--------|
| R1 | 존재하지 않는 모듈 import | citation_pipeline.py `run_pipeline` | `from enricher import enrich_paper`, `from acquirer import acquire_body` → ModuleNotFoundError (`enricher.py`/`acquirer.py` 없음) | 삭제하고 기존 `paper_acquisition.acquire_paper_body` + OpenAlex enrich 로직 복원 |
| R2 | batch_pipeline import 전체 실패 | batch_pipeline.py L51 | `from citation_pipeline import enrich_paper, ...` 7개명 전부 소실 → ImportError | citation_pipeline에 `enrich_paper/acquire_body/extract_and_filter/collect_scholar_cited_by/fetch_openalex_by_doi/load_env_key` 복원 또는 batch import 목록 수정 |
| R3 | 순환 import + 없는 함수 | citation_pipeline.py `run_pipeline` 말미 | `from batch_pipeline import collect_scholar_cited_by` (batch에 그런 함수 없음, 원래 citation→batch 방향이었음) | batch import 방향으로 되돌리고 함수명 일치시킬 것 |
| R4 | `save_to_obsidian` 미정의 변수 | citation_pipeline.py `save_to_obsidian` 본문 | `result.error/label/status/...`, `citation_graph_edges` 참조하나 스코프에 없음 → NameError | `result`→`verification`, `citation_graph_edges`→`paper.citation_graph_edges`로 교체 |
| R5 | `filter_by_rq` 호출 규격 불일치 | `run_pipeline` ⑤ | `filter_by_rq(text_or_path=paper.sha256, rq=...)` — 실제 시그니처는 `(text_or_path, research_question, ...)`이며 sha256 해시를 경로로 전달 → TypeError/파일없음 | `filter_by_rq(pdf_path, research_question, threshold=..., max_passages=...)`로 복원 |
| R6 | scite 메서드명 불일치 | `verify_with_scite` | `scite.editorialNotices(...)` 호출이나 실제 메서드는 `editorial_notices` → AttributeError | `editorial_notices`로 호출 |
| R7 | `import argparse` 누락 | citation_pipeline.py 상단/`main` | `main()`에서 argparse 사용하나 import 없음 → NameError | `import argparse` 추가 |
| R8 | `_vault_sha256_cache` 미정의 | `build_sha256_set` | 캐시 dict 전역 정의 삭제됨 → NameError | `_vault_sha256_cache: dict[str, set[str]] = {}` 복원 |
| R9 | evidence 필드 후퇴 | `SciteVerification`/`verify_with_scite` | `evidence_snippets: list[str]`로 바뀌고 채우 never; `source_version`/`retrieved_at` 없음; 라벨 로직 삭제됨(`tally.get("label")`은 항상 없음) | 이전 tally 비율 기반 라벨 + snippet 수집 + `retrieved_at` 복원 |
| R10 | `CanonicalPaper.authors` 삭제 + title None | dataclass | `paper.title[:60]`에서 None 슬라이싱 TypeError; 저자 정보 소실 | `authors` 필드 복원, title None 가드 |
| R11 | scite_client 테스트 깨짐 | scite_client.py `_standalone_test` | 개명 후에도 `scite.citing_papers(...)` 호출 → AttributeError | `citation_graph`로 수정 |
| R12 | `get_unique_filepath` 충돌 버그 | citation_pipeline.py | base 존재 시에도 suffix glob이 base와 매칭 안 돼 원본 경로 반환 → 덮어쓰기 | `base_path.exists()` 검사 우선으로 복원 |

### 코드 수정 지시 (적용 순서)
1. `citation_pipeline.py`: R7→R8→R1→R4→R5→R6→R9→R10→R12 순으로 수정 후 `py_compile`.
2. `scite_client.py`: R11 (테스트 함수명) 수정.
3. `batch_pipeline.py` import 목록과 `citation_pipeline` 함수 집합 일치 확인 후 `python -c "import batch_pipeline"` 재검증.
4. 재검증 통과 후 본 섹션에 `RE-VERIFIED OK` 추기.

### RE-VERIFIED OK (수정 적용 후 재검증 통과)
- `py_compile`: 6개 파일 전부 OK (citation/batch/scite/paper_acquisition/text_extraction/academic_mcp_direct)
- 속성 점검: `MISSING=NONE` — enrich_paper/acquire_body/extract_and_filter/collect_scholar_cited_by/fetch_openalex_by_doi/fetch_openalex_by_title/load_env_key/canonicalize_paper/verify_with_scite/save_to_obsidian/build_sha256_set/get_unique_filepath 전부 존재
- `verify_with_scite` 동기 래퍼 복원 (batch 호환), `extract_and_filter` async 유지 (await 호출과 일치)
- `import batch_pipeline` → **BATCH_IMPORT_OK** (ImportError 해소)
- 추가 수정(재검증 과정에서 반영): `acquire_body`가 `pdf_path`도 저장하도록 수정(raw 복사 경로 복구), `enrich_paper`에 저자 보강·`referenced_works` 추출·초록 복원 버그 수정, `save_to_obsidian` evidence 렌더링 버그(`ev.get('context',''[:200])`→`[:200]` 슬라이싱) 수정, frontmatter에 `evidence_excerpt`/`retrieved_at` 추가
- R1–R12 전부 해소. 남은 원본 리뷰 항목(P0 #2 browser_exec 실구현, P0 #4 RQ 3-class/method_similarity, TF-IDF, 출력 스키마 확장)은 다음 단계 과제로 유지.

### 후속 구현 (Step ⑤ RQ 분류 + 출력 스키마 + 수집 폴백 — 적용 완료)
- `text_extraction.py`: `classify_rq_similarity` (스펙 Q1-Q3 JSON 프롬프트, enum 검증, 실패 시 결정적 휴리스틱 폴백), `method_jaccard` (≥0.5 high / ≥0.3 medium), `compute_tfidf_similarity` (sklearn 있으면 TF-IDF, 없으면 Jaccard 폴백), `decide_verdict` (unrelated→탈락 / low-confidence→review / same+thr 또는 tfidf≥0.35→kept) 추가. `filter_by_rq(include_review)` 확장 — False면 kept만(기존 호출 하위호환), True면 review 항목을 verdict와 함께 뒤에 추가. filtered_out은 항상 제외 (스모크테스트에서 발견한 review 오염 버그 수정).
- `citation_pipeline.py`: `FilteredPassage`에 rq_class/method_similarity/tfidf_score/confidence/filter_reason/filter_verdict 추가 및 매핑. `run_pipeline`은 include_review=True로 호출 후 kept만 저장, review는 `review_passages`로 분리, `stats{collected/deduped/with_doi/with_pdf/verified/needs_review/retracted_flagged}` 반환. 수집: SERPAPI_KEY 있으면 SerpApi cites 우선 → 실패 시 OpenAlex, 전 구간 `_get_with_backoff`(2s→4s→8s) 적용. (browser_exec 실크롤링은 하네스 도구 필요 — TODO 유지.)
- 오프라인 스모크테스트 통과: decide_verdict 4케이스, heuristic same/unrelated, filter kept/review/unrelated 분리, review 단독 케이스(related+low) 확인. LLM 경로(키 필요)는 미검증 — 실키 환경에서 1건 확인 필요.

### 정기 리뷰 (2026-09-09, 코드 수정 없음 — 읽기 전용)
**대상**: text_extraction.py (21:16), citation_pipeline.py (21:06), scite_client.py (21:03), SKILL.md (09-07 추가분), plans_citation.md
**검증**: `py_compile` 6파일 OK, `import batch_pipeline` OK. remote_codex는 본 환경에 없음(호출 수단 부재) → 수동 리뷰로 대체.
**총평**: R1–R12 수정분 + 후속 구현분 모두 유지됨. 컴파일·import 정상. 남은 것은 스펙-코드 간 드리프트와 reasoning 모델 호환 리스크.

| # | 등급 | 위치 | 내용 |
|---|------|------|------|
| F1 | P1 | text_extraction.py `similarity_filter` | reasoning 모델(`auto/best-reasoning`) 호환 리스크: `max_tokens: 10` + `temperature: 0.0` + 정규식 첫 float 추출. reasoning 모델은 긴 추론 후 답변하거나 temperature 고정을 미지원할 수 있어 chunks가 조용히 탈락(`None`→skip)하거나 추론 과정의 숫자를 점수로 오인할 수 있음. 실키 환경에서 1건 확인 전까지 미검증 상태 |
| F2 | P2 | text_extraction.py `filter_by_rq` | chunk당 LLM 2회 호출(유사도 1 + 분류 1). 키 설정 시 비용·지연 2배. 1회 호출로 점수+분류 통합은 향후 최적화 후보 (동작은 정상) |
| F3 | P3 | text_extraction.py docstring | `similarity_filter` docstring이 여전히 "api_url None→DEFAULT_LLM_URL"이라 서술. 실제 해석 순서는 인자 > `LLM_API_URL` > 기본값. 문서만 어긋남 |
| F4 | P1 | plans ① vs `canonicalize_paper` | plans의 레벤슈타인 ≥0.85 + 저자/연도 매칭 + version-of-record 선별이 코드에 없음. 코드는 DOI 정규화+title strip만 수행 |
| F5 | P1 | plans ② vs `collect_scholar_cited_by` | 캡차 감지·중단 반환·페이지네이션 미구현 (browser_exec 하네스 의존). SerpApi 경로는 단일 호출(`num`≤100)이라 100건 초과 인용은 잘림 |
| F6 | P2 | plans ⑤ vs 코드 | "매 실행 `log.md` 스냅샷" 미구현. 판정 필드는 JSON에 보존되나 실행 단위 스냅샷 파일 없음 |
| F7 | P1 | plans ⑥ vs `_verify_scite_async` | `citation_graph` 교차검증 + `unconfirmed_by_scite` 플래그 미구현. 현재 `paper_by_doi` 단일 조회만 수행 |
| F8 | P2 | 라벨 3원화 | plans(`verified\|partially_verified\|...`) vs 코드(`supporting/contrasting/mixed/...`) vs SKILL(09-07 `scite_unreachable` 추가). 동일 상태의 이름이 문서마다 다름 |
| F9 | P3 | citing 스키마 비대칭 | OpenAlex 경로 dict에 `url_scholar`/`snippet` 키 없음 (SerpApi 경로에만 존재). 다운스트림 키 접근 시 `KeyError` 주의 → `.get` 사용 권장 |
| G1 | 양호 | `cited_by_api_url` 사용 | API 제공 URL이 이미 `filter=cites:` 형식이라 SKILL 경고(`/works/{id}/cited_by` 오용)와 무관. 코드 경로 정상 |
| G2 | 양호 | batch_pipeline | import 집합 일치 확인 (`IMPORT_OK`). 수정 없이 호환 유지 |

**조치**: 코드 수정 없이 본 기록 + plans_citation.md에 "구현 현황(2026-09-09)" 반영. F1은 실키 테스트 시 최우선 확인 항목으로 지정.

### 실호출 테스트 (2026-09-09, 키 있음·서버 불통)
- 설정 확인: `LLM_API_KEY` 있음(35자), `LLM_API_URL`은 `.env`에 없음 → 호출 시 `api_url` 인자로 `http://llm-router.example.local:20128/v1/chat/completions` 직접 지정.
- `similarity_filter` 실호출: `urlopen error [WinError 10060]` (연결 시간 초과) → 예외 처리 후 키워드 폴백 동작, `SCORE=0.375` 반환. 폴백 경로 정상 작동 확인.
- TCP 프로브 (`llm-router.example.local:20128`, 5초): `TimeoutError` — 서버 자체가 이 머신에서 도달 불가. 원인 후보: VPN/네트워크 분리, 서버 미기동, 방화벽, IP:포트 오기.
- 결론: F1(reasoning 모델 호환)은 **여전히 미검증**. 서버 도달 가능해져야 확인 가능. `.env`에 `LLM_API_URL=http://llm-router.example.local:20128/v1/chat/completions` 추가 권장 (현재 미설정이라 인자 없이 호출하면 OpenAI 기본값으로 나감).

### 실호출 테스트 2차 (서버 가동 후 — F1 확정, 코드 미수정)
- `similarity_filter` 실호출 → `Expecting value: line 1 column 1 (char 0)` → 폴백 `SCORE=0.375`. 원시 응답 확인 결과, 게이트웨이가 `stream` 미요청에도 **SSE 스트리밍**(`data: {...}` + `data: [DONE]`)으로 반환. 코드의 `json.loads(전체 body)`와 비호환 → F1 확정.
- 스트림 내용: chunk 2개 + `[DONE]`, **content delta 없음** (빈 delta 후 즉시 stop). `max_tokens: 10`이 reasoning 모델에 너무 작아 추론 토큰에 소진됐거나 게이트웨이가 reasoning을 스트립한 것으로 추정. 라우팅된 실모델은 `gemini-3-flash-preview`.
- 수정안 (미적용, 승인 후): ① 응답 파서 SSE 대응 (`data:` 라인 누적 → `delta.content` 결합 → `[DONE]` 종료, 단일 JSON도 계속 지원), ② `max_tokens` 상향(예: 1000, reasoning 여유), ③ `temperature`는 reasoning 모델에서 제외/조건부 (게이트웨이는 현재 200 허용하나 모델별 상이). 예상 효과: similarity 점수 정상 파싱 + `_classify_via_llm` JSON 수신.

### 실호출 테스트 3차 (수정 적용 후 — F1 해소)
- 적용: `_parse_chat_content` (SSE+단일 JSON 양립), `_chat_post` 공용화, `max_tokens` 10/200→1000, reasoning 모델(`reasoning`/`thinking`/o1·o3·o4 포함 시) `temperature` 제외, `stream: False` 명시. 숫자 추출은 마지막 float 우선(추론 과정 숫자 오인 방지).
- 오프라인 검증: SSE 샘플→`0.8` 파싱, reasoning 판별 True/False, 컴파일 OK.
- 실서버 검증: `similarity_filter` → `SCORE=0.8` (SSE 파싱·float 추출 정상). `classify_rq_similarity` → `same/high/high` + 한국어 reason 1줄 (JSON 파싱·enum 검증 정상).
- 결론: **F1 해소**. 남은 조건: `.env`에 `LLM_API_URL` 등록 시 인자 없이도 사내 게이트웨이로 호출됨.

### 후속 수정 적용 (F3–F9, 코드 수정)
- **F4 정준화 강화**: `_normalize_text_key` + `_title_similarity`(difflib, 스펙 ≥0.85) + `dedupe_papers`(DOI>OpenAlexID>정규화title+첫저자+year). `fetch_openalex_by_title`이 상위 5건 중 유사도+연도 가산으로 최적 선택. `enrich_paper`에 `locations[].version` 기반 version-of-record 판별 + 저자 보강 유지. `run_pipeline` 수집 후 dedupe 적용.
- **F7 교차검증**: `_verify_scite_async`에 `citing_dois` 인자 + `citation_graph(direction="in")` 조회 후 graph papers/edges 키 집합과 대조, 미포함 DOI를 `unconfirmed_by_scite`에 기록 (graph 실패 시 스킵). 수집(②)을 검증(⑥) 앞으로 이동. `stats`에 `unconfirmed_by_scite` 건수 추가.
- **F6 로그**: `write_run_log` 신설 — SKILL_ROOT/`log.md`에 실행 스냅샷 append (실패해도 파이프라인 계속).
- **F5 페이징**: SerpApi `start` 루프(20건씩), OpenAlex `per-page=200&page=` 루프. `max_results` 도달·빈 페이지·미만 수신 시 종료.
- **F8 라벨 통일**: `verification_status`를 plans 어휘로 (`verified/partially_verified/unverified/unverifiable_no_doi/retracted/scite_unreachable`). `label`은 tally 상세 유지. 토큰없음·예외→`scite_unreachable`, DOI없음→`unverifiable_no_doi`(단일+배치 공통).
- **F3+F9**: docstring 해석순서 갱신, OpenAlex 경로 dict에 `url_scholar/snippet: None` 추가로 SerpApi 경로와 키 대칭.
- **검증**: 6파일 컴파일 OK, `IMPORT_OK`, dedupe 4→2·유사도 1.0 오프라인 통과, **OpenAlex 실호출 통과** (제목 검색 최적 선택 score=1.00; 해당 레코드 연도는 2025로 등록되어 있어 연도 가산 미적용에도 제목으로 정확 선택).

---

## 읽기 전용 재리뷰 (2026-09-09, 코드 수정 없음)

**대상**: `src/` 전체 Python 코드와 최근 수정분

**검증 방법**:
- BERT DOI `10.18653/v1/N19-1423` 파이프라인 예시 실행 결과 대조
- 수동 OAuth 경로 직접 실행
- SerpApi Google Scholar 공식 API 문서와 요청/응답 스키마 대조
- OpenAlex 실응답 및 `filter=cites:W2963341956` 호출 대조
- 정적 코드 검토 및 별도 탐색 에이전트 교차 리뷰

### 주요 발견사항

| # | 등급 | 위치 | 내용 |
|---|---|---|---|
| N1 | Critical | `citation_pipeline.py:259-269`, `339-341` | 인용 수집 경로가 사실상 동작하지 않는다. SerpApi 코드는 공식 응답의 `inline_links.cited_by.cites_id` 대신 `organic_results[0].cited_by.cites`를 조회한다. 인증도 공식 문서가 요구하는 `api_key` 파라미터가 아니라 문서화되지 않은 `X-API-KEY` 헤더를 사용한다. OpenAlex 폴백은 최신 Work 응답에 없는 `cited_by_api_url`을 요구한다. 실제 BERT는 `filter=cites:W2963341956`에서 33,633건이 조회되지만 파이프라인은 0건을 반환했다. |
| N2 | Critical | `citation_pipeline.py:275-311` | SerpApi 결과 변환 코드가 `for r in batch` 바깥에 잘못 들여쓰기되어 페이지당 마지막 결과 한 건만 추가된다. 최대 20건 중 19건이 조용히 누락될 수 있다. |
| N3 | Critical | `citation_pipeline.py:644-674`, `1010-1012`; `batch_pipeline.py:193-196` | async 파이프라인 내부에서 동기 `verify_with_scite()`가 같은 스레드에 새 이벤트 루프를 만들어 `run_until_complete()`를 호출한다. Python이 이를 거부하여 DOI 기반 검증이 `scite_unreachable`로 강등되고 coroutine/loop가 누수된다. 예시 실행에서 `_verify_scite_async was never awaited` 경고가 재현됐다. |
| N4 | High | `scite_client.py:82-101` | `streamable_http_client(...).__aenter__()`의 반환값인 streams 튜플만 저장하고 실제 context manager를 잃는다. 종료 시 튜플에 `__aexit__()`을 호출하여 예외가 발생하고 HTTP client 정리도 건너뛸 수 있다. 초기화 실패 경로도 열린 자원을 누수한다. |
| N5 | High | `citation_pipeline.py:746-756`, `785-813`, `870-874` | SHA256이 없는 같은 제목의 논문은 DOI가 달라도 기존 노트를 덮어쓸 수 있다. SHA256 8자 prefix 충돌도 덮어쓰기 가능하며, PDF는 중복 검사 전에 `copy2()`로 덮어쓴다. 노트/PDF 쓰기도 원자적이지 않다. |
| N6 | High | `paper_acquisition.py:25-88` | `async with client or AsyncClient()`가 호출자 소유 client까지 닫는다. 첫 요청이 실패하면 재시도에서 이미 닫힌 client를 사용하여 즉시 실패하고, 성공한 경우에도 호출자에게 닫힌 client가 반환된다. |
| N7 | High | `academic_mcp_direct.py:276-356` | startup/read timeout이 executor의 blocking `readline()`을 실제로 중단하지 못한다. timeout/EOF 경로의 동기 `stderr.read()`는 이벤트 루프를 무기한 막을 수 있고, 일부 `__aenter__` 실패는 subprocess를 정리하지 않는다. |
| N8 | High | `academic_mcp_direct.py:320-356` | 요청 잠금과 응답 ID 검증이 없어 동시 호출 시 응답이 뒤섞일 수 있다. timeout으로 취소된 executor reader가 다음 응답을 소비하면 이후 프로토콜이 영구적으로 어긋날 수 있다. |
| N9 | High | `scite_oauth_auth.py:208-225` | `main()` 후반의 지역 `import os` 때문에 수동 모드의 앞선 `os.environ` 접근이 `UnboundLocalError`를 발생시킨다. 직접 실행으로 재현했다. |
| N10 | High | `scite_oauth_auth.py:87-95` | access token 앞 40자를 콘솔에 출력하여 terminal history/수집 로그에 bearer credential이 노출될 수 있다. 실패 응답 본문도 그대로 출력한다. |
| N11 | Medium | `citation_pipeline.py:225-235`, `264-270` | OpenAlex와 Scholar/SerpApi 검색 결과를 최소 제목 유사도·저자·연도로 검증하지 않고 최상위/최고 점수 결과를 무조건 선택한다. 모호한 제목에서 다른 논문의 인용을 저장할 수 있다. |
| N12 | Medium | `citation_pipeline.py:573-599` | correction 또는 expression of concern을 포함한 모든 editorial notice를 `retracted`로 처리한다. 문서의 `concern_raised` 상태는 실제 판정에 사용되지 않는다. |
| N13 | Medium | `paper_acquisition.py:93-152`, `272-286` | `/pdf/file.pdf` 같은 상대 링크를 기준 URL과 결합하지 않고 다운로드한다. `timeout` 인자도 `web_extract`에 적용되지 않으며 동기 호출이 async 이벤트 루프를 막는다. |
| N14 | Medium | `paper_acquisition.py:44-77` | 응답 크기 제한 없이 전체 파일을 메모리에 적재한다. URL 마지막 segment를 query 제거/디코딩/Windows 파일명 정제 없이 사용하여 `paper.pdf?download=1` 같은 정상 URL도 저장 실패할 수 있다. |
| N15 | Medium | `batch_pipeline.py:152-158`, `222-228`, `311-318` | DOI 없는 논문은 progress에 빈 문자열로 기록하지만 외부 루프는 제목을 식별자로 사용하므로 resume 때마다 다시 처리된다. DOI 정규화 차이도 완료 판정을 우회한다. |
| N16 | Medium | `batch_pipeline.py:81-89`, `172-224` | 손상되거나 스키마가 다른 progress 파일은 경고 없이 무시되고 이후 덮어써진다. 저장 단계의 일부 예외만 failed로 기록하며 enrich/acquire/filter/verify 예외는 현재 논문 상태를 남기지 않고 배치 전체를 중단시킨다. |
| N17 | Medium | `text_extraction.py:44-76`, `100-139`, `511-521` | PyMuPDF 문서는 페이지 처리 예외 시 닫히지 않는다. 인식되지 않은 섹션은 `unmatched`에 들어간 뒤 필터 대상에서 제외된다. raw text를 먼저 `Path`로 취급해 긴 문자열이나 `.pdf`로 끝나는 본문이 경로 오류를 낼 수 있다. |
| N18 | Medium | `citation_pipeline.py:190-197` | DOI 조회 URL에 `mailto`를 `&mailto=`로 붙여 잘못된 URL을 만든다. DOI와 mailto도 URL encoding하지 않는다. `run_pipeline()`의 `mailto`는 대부분의 enrich/수집 호출에 전달되지 않는다. |
| N19 | Medium | `citation_pipeline.py:688-743` | authors를 YAML flow sequence에 따옴표 없이 삽입하여 쉼표·콜론·대괄호가 있는 이름이 frontmatter를 깨뜨릴 수 있다. 검증 실패 상태에도 항상 `scite-verified` 태그가 붙는다. |
| N20 | Medium | CLI 전반 | Windows 기본 CP949 콘솔에서 이모지 출력 때문에 파이프라인이 시작 직후 `UnicodeEncodeError`로 종료된다. `PYTHONIOENCODING=utf-8` 설정 시에만 예시 실행이 진행됐다. |

### 추가 품질 문제

- `academic_mcp_direct.py:105-118`: 소스별 검색 실패를 `pass`로 숨겨 부분 결과를 정상 결과처럼 반환한다.
- `scite_client.py:49-64`: 첫 MCP content block만 읽고 모든 파싱 오류를 `None`으로 바꿔 서버 오류와 미검색을 구분하지 못한다.
- `scite_discover_tools.py`, `scite_test_query.py`, `scite_debug_result.py`: 생성한 caller-owned `httpx.AsyncClient`를 명시적으로 닫지 않는다.
- `scite_oauth_auth.py:100-129`: `.env` 디코딩 실패 시 기존 설정을 빈 상태에서 재작성할 수 있고, 주석·순서·인용 형식이 손실된다. 저장은 원자적이지 않으며 `SCITE_CLIENT_ID`도 중복 출력된다.
- `scite_oauth_auth.py:52-68`, `135-145`: OAuth `state`가 고정값이며 callback에서 검증되지 않는다. class-global `captured_code`도 새 인증 전에 초기화되지 않는다.
- async 파이프라인에서 PDF 추출, SHA256, sklearn, 동기 `urllib` LLM 호출, `time.sleep()`이 이벤트 루프를 장시간 차단한다.

### 테스트 공백

자동화된 테스트 스위트와 dependency manifest가 없다. 현재 테스트 파일은 외부 서비스와 실제 자격 증명에 의존하는 smoke script이며 assertion이 없다.

우선 필요한 회귀 테스트:

1. async `run_pipeline`/배치 내부 scite 검증과 정상 context cleanup
2. SerpApi 실제 스키마, 인증, 20건 페이지, 다중 페이지, 401/429 처리
3. OpenAlex `filter=cites:{openalex_id}` 수집과 페이지네이션
4. caller-owned HTTP client, retry, query 포함 파일명, 대용량 응답, 상대 PDF URL
5. 같은 제목/no-hash/SHA prefix 충돌에서 기존 노트·PDF 비덮어쓰기
6. DOI 없는 논문과 손상된 progress 파일의 resume
7. Academic MCP startup/read timeout, cancellation, 동시 호출, response ID 불일치
8. 수동 OAuth, state 검증, token redaction, `.env` 보존과 원자적 저장
9. 헤더 없는 PDF, 추출 예외 시 자원 정리, 긴 inline text
10. 특수문자가 포함된 저자·제목·DOI의 YAML round-trip

### 최종 판단

현재 구현은 문법/import 수준에서는 실행 가능하지만, 인용 수집과 scite 검증이라는 핵심 경로에 blocking 결함이 있어 운영 사용 준비 상태로 보기 어렵다. 우선순위는 **인용 수집 복구 → async scite 및 client lifecycle 수정 → Obsidian 덮어쓰기 방지 → PDF/Academic MCP 자원 관리 → OAuth 보안과 자동화 테스트** 순이다.
