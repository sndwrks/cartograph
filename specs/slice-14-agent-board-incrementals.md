# Slice 14 — Agent message board via MCP + git-hook incrementals

## Goal

M5: agents coordinate through the graph. The MCP server gains `post_message` and `read_board` with self-registration, the SPA side panel shows discussion threads anchored to symbols, and a git post-commit hook keeps the graph fresh by driving incremental ingest (with threshold-gated metrics and enrichment). A repo-level `CLAUDE.md` teaches assistants the house rules.

## Depends on

Slices 09 (MCP server), 12 (panel), 13 (enrich chaining). Slice 08's message/agent query layer does the heavy lifting.

## Spec references

`initial-spec.md` §6 (board tools, self-registration, instructed behaviors), §8 (incremental workflow).

## Requirements

### 1. MCP tools — additions to `mcp_server/tools.py`

1. `post_message(agent_name: str, body: str, subject: str | None = None, thread_id: int | None = None, node_qualified_name: str | None = None)`:
   - **Self-registration:** `get_or_create_agent(agent_name)` (slice 08) — first post creates the agent; every post bumps `last_seen`.
   - `node_qualified_name` resolves to a node id (same resolution as `get_node`; unresolvable → structured error listing candidates); `thread_id` follows slice-08 root-rewriting semantics.
   - Returns the created message (id, thread root id, timestamps).
   - Description: "Post to the agent coordination board. Anchor to a symbol with node_qualified_name when the message is about specific code."
2. `read_board(limit: int = 20, thread_id: int | None = None, node_qualified_name: str | None = None, agent_name: str | None = None, since: str | None = None)`:
   - No thread_id → thread roots newest-first with reply counts; with thread_id → the full thread oldest-first. `since` is ISO-8601, filters on created_at.
   - Description: "Read the agent coordination board. Check for existing threads about a symbol before starting work on it."
3. Tool count is now seven — the complete spec §6 set.

### 2. SPA — panel Discussion section live (`NodeDetail.tsx`, new `ThreadList.tsx`)

1. Selected node → `GET /api/v1/messages?node_id=` (slice 08): threads anchored to the symbol, collapsed to root + reply count; expanding fetches the thread. Render agent name, relative time, subject/body.
2. Empty state: "No discussion. Agents can anchor threads here via MCP."
3. Read-only in the SPA for v0.1 (posting is an agent act via MCP) — note this in the empty state.

### 3. Git-hook incrementals — `scripts/`

1. `scripts/post-commit` (template, executable) + `scripts/install-hook.sh` that symlinks it into a target repo's `.git/hooks/`. The hook:
   - Collects changed files: `git diff-tree --no-commit-id --name-only -r HEAD`.
   - Calls `docker compose run --rm api uv run python -m cartograph.ingest run --repo "$CARTOGRAPH_REPO" --files <changed...>` (compose project dir via `CARTOGRAPH_COMPOSE_DIR` env; both variables documented at the top of the script). Skips silently when compose isn't running (`docker compose ps -q api` empty) — a hook must never block a commit; always `exit 0`, logging failures to `.git/cartograph-hook.log`.
2. Chaining inside `ingest run` (not the hook): after load+resolve, invoke the metrics job passing `--changed-edges <edges_added + edges_deleted>` so clustering only re-runs past the slice-06 threshold; when `--enrich` is set (hook passes it), run enrich phases `summaries embeddings docs` for the repo (community labels stay put — on-demand only, per spec §10 recommendation). Record phase timings in the run's `stats`.
3. `trigger` on the run row: hook-invoked runs record `trigger="hook"` (flag `--trigger hook`).

### 4. `CLAUDE.md` (repo root, shipped for consumers of the graph)

Written for assistants connected to the MCP server; must instruct: call `kb_lookup` before assuming any acronym/internal term; treat `name_match` edges as unproven hints and `llm_inferred` as judgment, prefer `resolved`; check `read_board` for existing threads about a symbol before modifying it, and `post_message` significant findings anchored to the symbol. Keep it under ~40 lines.

## Files

- `backend/src/cartograph/mcp_server/tools.py` (+2 tools), `backend/tests/mcp/test_board_tools.py`
- `backend/src/cartograph/ingest/__main__.py` (+ `--trigger`, `--enrich`, metrics chaining)
- `web/src/components/{NodeDetail.tsx (edit),ThreadList.tsx}`
- `scripts/{post-commit,install-hook.sh}`
- `CLAUDE.md`, `README.md` (hook setup section)

## Acceptance criteria

1. MCP tests: `post_message` from an unknown agent name creates the agent (visible via `GET /api/v1/agents`) and the message; replying to a reply lands on the thread root; `read_board` filtered by `node_qualified_name` returns the anchored thread; `since` filters; bad node name → structured error with candidates.
2. Live loop: via a real MCP client, post a message anchored to a fixture symbol → select that symbol in the SPA → the thread appears in the panel's Discussion section; expanding shows the reply.
3. Hook: in a scratch git repo registered + mounted as a cartograph repo, `install-hook.sh`, commit a change to one file → an `ingest_runs` row with `trigger="hook"` appears, only that file re-ingested; commit a whitespace-only change → run records zero deltas and clustering skipped (threshold gate); with compose stopped, committing still succeeds instantly.
4. `--enrich` chained run touches only changed nodes (fake-client counts, per slice 13).
5. Full-suite green: `uv run pytest` (backend) and `npm run build` (web).

## Out of scope

- SPA-side posting UI, auth per agent, message editing.
- Scheduled/CI ingestion (the hook is the v0.1 trigger; CI is a doc note).
- Tier-2 LSP resolution (future spec, M6).
