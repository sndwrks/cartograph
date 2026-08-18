# Slice 13 — Tier-3 enrichment & hybrid search

## Goal

The LLM pass: `python -m cartograph.enrich` writes summaries for symbols, embeds them with Voyage `voyage-code-3`, labels communities, ingests docs/config as graph nodes, and embeds KB entries. With embeddings in place, semantic and hybrid search go live, the KB lookup gains its vector fallback, and node detail gains related KB terms. This is the only slice that spends API money, so caching on content hash is a hard requirement, not an optimization.

## Depends on

Slices 07 and 08 (search/KB plumbing with declared-but-stubbed semantic paths). Slice 06 (communities to label).

## Spec references

`initial-spec.md` §3 Tier 3, §4 (embedding config), §5 (hybrid search, KB fallback).

## Requirements

### 1. Job CLI — `cartograph/enrich/__main__.py`

`python -m cartograph.enrich --repo NAME [--phase summaries|embeddings|communities|docs|kb|all] [--limit N]`

Default `all` runs phases in that order. Each phase is independently resumable (idempotent by cache checks). Requires `ANTHROPIC_API_KEY` (summaries, labels, doc linking) and `VOYAGE_API_KEY` (embeddings); fail fast with a clear message if the needed key is missing for the requested phase. Add `anthropic` and `voyageai` to `pyproject.toml`.

### 2. Phase: summaries

1. Scope: symbol nodes (`class`, `function`, `method`, `module`) whose source span exceeds a threshold (config `SUMMARY_MIN_LINES`, default 3) — trivial one-liners aren't worth tokens.
2. **Cache rule:** skip nodes where `summary_source_hash == content_hash` and `summary IS NOT NULL`. After writing a summary, set `summary_source_hash = content_hash`.
3. Prompt: read the symbol's source from `root_path` + `file_path` + line span; ask for a 1–3 sentence summary of purpose and role (not a line-by-line description); model `claude-sonnet-5`; batch multiple symbols per request where convenient but keep one summary ↔ one node attribution exact. Handle rate limits with backoff; a failed node logs and continues (the run reports a failure count, exits 0 if partial, per-phase counts in output).
4. Modules get summarized from their top-level docstring + symbol list when the file is too large to inline (cap prompt source at ~200 lines with head/tail elision).

### 3. Phase: embeddings

1. Scope: nodes with a summary whose `embedding IS NULL` **or** whose summary changed (track by re-embedding whenever the summaries phase rewrote the node — simplest correct rule: embeddings phase processes nodes where `embedding IS NULL OR summary_source_hash <> embed_source_hash`... since there is no `embed_source_hash` column, use this rule instead: the summaries phase **nulls `embedding`** whenever it rewrites a summary; the embeddings phase then just processes `summary IS NOT NULL AND embedding IS NULL`).
2. Voyage `voyage-code-3`, `output_dimension=1024` (must equal `EMBED_DIM`; assert at startup), input type `document`; batch up to 128 texts per call. Embed the text `f"{qualified_name} ({kind}): {summary}"`.
3. Search-side query embedding uses input type `query` (see §7).

### 4. Phase: communities

For each community lacking a label (or all with `--force`): gather its top ~15 members by pagerank (name, kind, summary) + inter-community neighbor labels; ask claude-sonnet-5 for a 2–4 word label ("Payments pipeline") and a 1–2 sentence summary; write to `Community.label/summary`. Slice 06's carry-over keeps these stable thereafter.

### 5. Phase: docs

1. Walk the repo for non-code artifacts: `README*`, `docs/**/*.md`, `*.adoc`, ADR folders, `*.sql`, and config files (`*.toml`, `*.yaml`, `*.yml`, `*.json` at repo root and `config/`-like dirs; same deny-list as slice 05).
2. Create `doc` nodes (markdown/adoc) and `config` nodes (sql/config) — kind, name = filename, qualified_name = repo-relative path, `content_hash`; cached by hash like code files (unchanged docs are skipped entirely).
3. For each new/changed doc: prompt claude-sonnet-5 with the doc text (capped) + a candidate symbol list (trigram-matched repo symbols mentioned in the text) to identify which code entities the document genuinely references; create `references` edges doc → symbol tagged **`llm_inferred`** (never `resolved`).
4. Docs get summaries + embeddings through the same phases (they satisfy the scope rules above).

### 6. Phase: kb

Embed KB entries (`term + ": " + definition`) where `embedding IS NULL`; KB create/update in the API (slice 08) nulls the embedding so this phase re-embeds edits.

### 7. Search goes live — edits in `query/search.py`

1. `search_semantic(repo, q, kinds, limit)`: embed `q` via Voyage (input type `query`), `ORDER BY embedding <=> :qvec` (cosine, HNSW index), over nodes with embeddings; return scores as `1 - distance`.
2. `search_hybrid`: run text + semantic, merge with the slice-07 RRF function, return `source: "hybrid"` and drop the `degraded` flag from the response.
3. `mode=semantic` returns real results (501 removed).
4. **KB lookup fallback:** step 3 of slice-08's lookup becomes vector search over KB embeddings (top 5, cosine), `match: "vector"` — steps 1–2 (exact, alias) unchanged; the PSN test must still pass byte-identically.
5. New endpoint `GET /api/v1/nodes/{id}/related-kb?limit=5`: cosine match between the node's embedding and KB embeddings → the slice-12 panel section renders it (small SPA change: replace the placeholder with the fetch).

### 8. Ingest integration

`cartograph.ingest run` gains `--enrich` flag chaining the enrich job after load+resolve (used by slice 14's hook). A change to one file must only re-summarize/re-embed that file's nodes — this falls out of the cache rules, but is an explicit acceptance test.

## Files

- `backend/src/cartograph/enrich/{__init__.py,__main__.py,summaries.py,embeddings.py,communities.py,docs.py,kb.py,llm.py,voyage.py}`
- `backend/src/cartograph/query/{search.py (implement),kb.py (fallback),graph.py (related-kb)}`
- `backend/src/cartograph/api/routers/graph.py` (related-kb route), `search.py` (un-stub)
- `web/src/components/NodeDetail.tsx` (related-KB section live)
- `backend/tests/enrich/` — LLM and Voyage clients behind small interfaces (`llm.py`, `voyage.py`) so tests inject fakes; **no test may hit real APIs**

## Acceptance criteria

1. With fake LLM/embedding clients: full enrich over ingested `py_sample` writes summaries only to above-threshold symbols, sets `summary_source_hash`, embeds them 1024-dim, labels every community, creates doc nodes for a fixture README with `llm_inferred` references edges to symbols it mentions, embeds KB entries.
2. **Cache proof:** immediate re-run makes zero LLM and zero embedding calls (assert on the fake clients' call counts). Touch one file, re-ingest, re-enrich → only that file's nodes hit the fakes.
3. Hybrid search test (fake embeddings crafted so semantic and text rank differently): RRF order correct, `degraded` gone, `mode=semantic` no longer 501.
4. **PSN regression:** slice-08's exact/alias tests pass unchanged; a term with no exact/alias hit now returns `match: "vector"` results.
5. `GET /nodes/{id}/related-kb` returns the planted nearest KB entry; the panel section renders it.
6. Live smoke (manual, real keys, tiny repo): `docker compose run --rm api uv run python -m cartograph.enrich --repo py_sample --limit 5` produces real summaries; document observed cost order-of-magnitude in the run output.

## Out of scope

- Resolving `name_match` edges via LLM (spec §3 mentions it; deliberately deferred past M5 — the confidence model already communicates uncertainty).
- Message board (slice 14).
- Re-embedding on model change / EMBED_DIM migration tooling.
