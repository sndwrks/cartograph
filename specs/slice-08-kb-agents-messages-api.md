# Slice 08 — KB, agents, messages, runs API

## Goal

The non-graph API surface: knowledge-base CRUD with deterministic lookup, agents registry CRUD, the message board with threading and node anchoring, and read-only ingest-run status. All through new query-layer modules.

## Depends on

Slice 02 (models). Router wiring joins slice 07's app; can be built in parallel with 07 if the mounting point exists.

## Spec references

`initial-spec.md` §5 (KB lookup determinism — "the PSN case must be deterministic"; agents/messages; ingest runs).

## Requirements

### 1. Knowledge base — `query/kb.py`, `api/routers/kb.py`

```
POST   /api/v1/kb                    create {term, definition, aliases?, category?}
GET    /api/v1/kb?category=&limit=&offset=   list
GET    /api/v1/kb/{id}               read
PUT    /api/v1/kb/{id}               update
DELETE /api/v1/kb/{id}               delete
GET    /api/v1/kb/lookup?term=PSN    lookup — the special one
```

Lookup semantics (order is the contract):

1. Exact case-insensitive term match (`lower(term) = lower(:q)`, backed by the unique `ix_kb_term_lower` index) → return that single entry, `match: "exact"`.
2. Alias match: any element of `aliases` equal case-insensitively → `match: "alias"`. If multiple entries alias-match, return all, ordered by term.
3. Vector fallback: **not yet implemented** — until slice 13, return `{match: "none", results: []}` with HTTP 200. Slice 13 replaces step 3 with embedding search; steps 1–2 must remain untouched then (the determinism guarantee).

Create/update must reject a term that collides case-insensitively with an existing term (the unique index enforces it; surface as HTTP 409, not 500). `category` is free text but document the expected values: `acronym | domain | convention`.

### 2. Agents — `query/agents.py`, `api/routers/agents.py`

```
POST   /api/v1/agents        create {name, role?, metadata_json?}   (name unique → 409 on dupe)
GET    /api/v1/agents        list
GET    /api/v1/agents/{id}   read
PUT    /api/v1/agents/{id}   update (role, status, metadata_json; sets last_seen=now() when status changes)
DELETE /api/v1/agents/{id}   delete
```

Also a query-layer function `get_or_create_agent(name)` (returns existing by name or creates with defaults) — slice 09/14's MCP self-registration uses it; implement and test it now.

### 3. Message board — `query/messages.py`, `api/routers/messages.py`

```
POST   /api/v1/messages      create {agent_id, body, subject?, thread_id?, node_id?}
GET    /api/v1/messages?thread_id=&node_id=&agent_id=&limit=50&offset=0
GET    /api/v1/messages/{id}
DELETE /api/v1/messages/{id}
```

Semantics:

- `thread_id` null = thread root. Posting with a `thread_id` that is itself a reply is **rewritten to the root's id** (threading stays flat, per the model comment). Posting with a nonexistent `thread_id`, `agent_id`, or `node_id` → 422.
- Listing without `thread_id` returns **thread roots only**, newest first, each with `reply_count` and `last_activity`. With `thread_id`, returns the root + all replies, oldest first.
- `node_id` filter: threads whose root **or any reply** is anchored to the node. Also `touch` the posting agent's `last_seen` on every create.

### 4. Ingest runs — `api/routers/ingest.py`

```
GET /api/v1/ingest/runs?repo=&limit=20   → newest first: id, repository, trigger, status, started_at, finished_at, stats
GET /api/v1/ingest/runs/{id}             → full record incl. error
```

Read-only; reuses `query/ingest.py` from slice 05.

## Files

- `backend/src/cartograph/query/{kb.py,agents.py,messages.py}` (+ additions to `ingest.py`)
- `backend/src/cartograph/api/routers/{kb.py,agents.py,messages.py,ingest.py}` + wiring in `app.py`
- `backend/tests/api/{test_kb.py,test_agents.py,test_messages.py,test_ingest_runs.py}`

## Acceptance criteria

1. **The PSN test (verbatim requirement):** create entry `term="PSN", definition="PositageNet — never any other expansion"`, plus a decoy entry whose definition text mentions "playstation network". `GET /kb/lookup?term=psn` returns exactly the PositageNet entry with `match: "exact"` — regardless of case, regardless of the decoy. Lookup of an alias returns `match: "alias"`. Lookup of an unknown term returns `match: "none"`, HTTP 200.
2. Case-insensitive duplicate term creation → 409.
3. Message threading: reply-to-a-reply lands on the root thread; root listing shows correct `reply_count`; `node_id` filter returns a thread anchored via a reply, not just roots.
4. Agents: duplicate name → 409; status update bumps `last_seen`; `get_or_create_agent` covered directly.
5. Ingest a fixture repo, then `GET /api/v1/ingest/runs?repo=py_sample` shows the run with stats.
6. `uv run pytest tests/api/` fully green (slice 07 tests unaffected).

## Out of scope

- KB vector fallback and embeddings (slice 13).
- MCP exposure of any of this (slices 09 and 14).
- Auth/multi-tenancy — the API stays open on the internal network per the spec's non-goals.
