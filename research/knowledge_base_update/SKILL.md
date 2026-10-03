---
name: knowledge_base_update
description: Update wiki/raw with research sources and RAG sync.
trigger: "when you need to add or refresh entries in a research‑oriented wiki or knowledge repository"
---
## Overview
Guides adding or refreshing entries in `wiki/raw` for scientific literature, datasets, or domain knowledge. Handles source fetching, extraction, markdown synthesis, reference bookkeeping, and optional RAG indexing.

### Typical Workflow
1. Gather sources (`web_search`, `web_extract`, cache files).
2. Extract key content (abstract, methods, results).
3. Synthesize concise Korean markdown (or user‑preferred language).
4. Write reference files under `references/`.
5. Write or patch the target index (`write_file`).
6. Run `rag_local.py` to refresh the retrieval index.
7. Verify with `read_file` / `open_preview`.

### Pitfalls & Gotchas
- Backup existing index before full rewrite.
- Keep PMID/PMCID and DOI in reference files.
- Ensure UTF‑8 encoding for Korean characters.
- After editing markdown, always re‑run the RAG script.

### Verification Steps
- `read_file` the updated index.
- `open_preview` to inspect layout.
- Execute a quick `rag_local.py` query.

### Example Reference (`references/glymphatic_mia_update.md`)
```
# Glymphatic & MIA Update (2024‑08‑19)
- Zhao et al., 2025, Front Psychiatry – DTI‑ALPS shows glymphatic dysfunction in ASD.
- Li et al., 2022 – Same finding, age‑correlated.
- Gumusoglu et al., 2017 – prenatal IL‑6 impacts microglia & GABA migration.
- Osman et al., 2024 – MIA elevates IL‑6 in placenta and fetal brain.

Mechanistic chain: MIA → maternal IL‑6 ↑ → fetal microglia activation & astrocytic AQP4 dysregulation → impaired perivascular clearance → ASD‑like phenotype.
```