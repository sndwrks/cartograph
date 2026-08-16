# Slice 05 — Ingest CLI & loader

## Goal

`python -m codegraph.ingest` registers repositories and loads them into the graph: walk files, run the tier-1 extractors, resolve references, and persist nodes and edges — incrementally, so a re-run after a small change touches only what changed. Every run writes an `ingest_runs` record. After this slice, M1 is complete: a real repository becomes a queryable graph.

## Depends on

Slices 02 (models/db) and 03 (extractor contract + Python). Works with slice 04 automatically via the extractor registry.

## Spec references

`initial-spec.md` §3 Tier 1 (incremental hashing, transactional replace), §8 (workflow, ingest_runs).

## Requirements

### 1. CLI — `codegraph/ingest/__main__.py`

argparse or typer, two subcommands:

- `register --name NAME --root PATH [--branch main]` → upsert a `repositories` row. `root_path` is the path **as seen inside the container** (the repo must be volume-mounted; document this in `--help` and the root README: mount the target repo into the api service, e.g. `-v /host/repo:/repos/myrepo`).
- `run --repo NAME [--files p1 p2 ...] [--full]` → ingest. Default is incremental (hash-based skip); `--files` restricts the walk to the given repo-relative paths (git-hook path, slice 14); `--full` ignores stored hashes.

Exit non-zero on failure, with the failure recorded on the run row.

### 2. File discovery

1. Walk `root_path` recursively; consider files with a registered extractor extension (slice 03/04 registry).
2. Respect ignores: skip `.git/`, and honor a default deny-list (`node_modules/`, `.venv/`, `dist/`, `build/`, `__pycache__/`, hidden dirs). Parsing `.gitignore` is optional; the deny-list is required.
3. Hash each file (sha256 of bytes). A file is **changed** if no `file` node exists for its path or the stored `content_hash` differs. `--full` marks everything changed.

### 3. Loading — per changed file, one transaction

For each changed file, inside a single transaction:

1. Delete the file's existing nodes: the `file` node and all symbol nodes with that `file_path` in this repository. Edge rows cascade via FK.
2. Insert the `file` node (kind `file`, name = basename, qualified_name = repo-relative path, `content_hash`) and the extraction's symbol nodes (`module`/`class`/`function`/`method`, with name, qname, `file_path`, line span, per-symbol `content_hash`).
3. Insert `contains` edges (confidence `resolved`): file → module, module → its top-level symbols, class → its methods/nested classes.

Unique constraint note: `(repository_id, qualified_name, kind)` — if two files claim the same qname+kind (happens with duplicated module names), last write wins with a logged warning; do not crash the run.

### 4. Reference resolution — cross-file pass

After all changed files are loaded:

1. **Dependent expansion.** Deleting a changed file's nodes cascades away edges *into* those nodes from unchanged files. Before resolving, expand the re-resolve set: any file that previously had an edge whose dst belonged to a changed file (capture this set by querying edges **before** the delete phase) gets its refs re-resolved too. Extraction is cheap and local — re-extract those dependent files in memory (do not rewrite their nodes; their hashes are unchanged).
2. Build the resolver input: `FileExtraction`s for changed + dependent files, plus a symbol table for the **whole repo** loaded from the `nodes` table (qname, kind, name — enough for `resolve.py`).
3. Run the slice-03 resolver. For each `CandidateEdge`, map qnames → node ids and insert `edges` rows (`rel`, `confidence`, `src_line`), using `ON CONFLICT DO NOTHING` against the `(src_id, dst_id, rel, src_line)` unique constraint. Before inserting, delete existing non-`contains` edges whose src node belongs to a changed or dependent file (they are being recomputed).

### 5. Run records

Wrap the whole run in an `IngestRun` row: created `running` at start; on success `succeeded` with `finished_at` and `stats` JSON:

```json
{"files_seen": 120, "files_changed": 3, "files_dependent": 2,
 "nodes_added": 14, "nodes_deleted": 12, "edges_added": 40, "edges_deleted": 35,
 "timings": {"walk": 0.4, "extract": 1.2, "load": 0.8, "resolve": 1.5}}
```

On exception: `failed`, `error` = traceback string, then re-raise for the non-zero exit.

### 6. Query layer seed

Create `codegraph/query/__init__.py` and `codegraph/query/ingest.py` holding the SQL this slice needs (symbol-table load, dependent-file lookup, run CRUD). The convention starts now: **ingest code calls query functions; no inline SQL elsewhere.**

## Files

- `backend/src/codegraph/ingest/{__init__.py,__main__.py,walker.py,loader.py}`
- `backend/src/codegraph/query/{__init__.py,ingest.py}`
- `backend/tests/ingest/test_ingest_incremental.py` (+ conftest reusing slice 02's DB fixtures; fixture repo can reuse `tests/extractors/fixtures/py_sample/`)

## Acceptance criteria

1. **Full ingest:** register `py_sample` as a repo, `run --repo py_sample`. Assert: one `file` node per fixture file, module/class/function/method nodes with correct qnames and spans, `contains` edges, cross-file `calls`/`inherits`/`imports` edges with expected confidences (mirror slice-03 resolver assertions, now via DB), and a `succeeded` `ingest_runs` row with non-empty stats.
2. **No-op re-run:** run again with no file changes → `files_changed == 0`, zero node/edge deltas, node ids unchanged (prove nothing was rewritten).
3. **Incremental:** modify one fixture file (add a function + a call into another module), re-run. Assert: only that file's nodes were replaced (other node ids stable), the new edge exists, and an edge **into** the changed file from an unchanged file still exists afterward (dependent-expansion proof).
4. **Deletion:** remove a fixture file, re-run with `--full` or with the file listed — its nodes are gone and no dangling edges remain.
5. Works end-to-end in compose: `docker compose run -v $(pwd)/backend/tests/extractors/fixtures/py_sample:/repos/py_sample --rm api uv run python -m codegraph.ingest register --name py_sample --root /repos/py_sample` then `run --repo py_sample` exits 0.

## Out of scope

- Metrics, PageRank, clustering (slice 06) — degree/pagerank columns stay at defaults.
- Tier-3 summaries/embeddings (slice 13).
- Git integration / changed-file detection from commits (slice 14 passes `--files` explicitly).
