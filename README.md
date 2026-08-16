# CodeGraph

A self-hosted codebase knowledge graph. CodeGraph ingests one or more repositories and
produces a persistent, queryable graph of code entities (files, classes, functions) and
their relationships (imports, calls, inheritance, references), enriched with vector
embeddings over LLM-written summaries. Humans explore the graph through a React SPA;
AI assistants query it through an MCP server backed by the same query layer.

## Quickstart

```sh
cp .env.example .env    # then edit passwords/keys
docker compose up --build
```

- API: http://localhost:8000/api/v1/health
- Web: http://localhost:5173 (nginx, proxies `/api` to the API)
- MCP: http://localhost:8765
- The database publishes **no host port**; all access goes through the API or MCP.
  Ad-hoc SQL: `docker compose exec db psql -U codegraph`.

## Development

The dev override mounts backend source for hot reload and runs the Vite dev server:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

The dev override also publishes Postgres on `127.0.0.1:5433` (loopback only) so
host-side tests can reach it. DB-touching tests use a dedicated `codegraph_test`
database created automatically by the test suite:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db
cd backend && uv run pytest
```

## Ingesting a repository

Repositories are read from **paths inside the api container**, so the target repo
must be volume-mounted. Register once, then run (re-runs are incremental,
hash-based; `--full` re-ingests everything, `--files p1 p2` restricts the walk):

```sh
docker compose run -v /host/path/myrepo:/repos/myrepo --rm api \
  uv run python -m codegraph.ingest register --name myrepo --root /repos/myrepo
docker compose run -v /host/path/myrepo:/repos/myrepo --rm api \
  uv run python -m codegraph.ingest run --repo myrepo
```

Every run writes an `ingest_runs` row with per-phase timings and node/edge deltas.

### Keeping the graph fresh with a git hook

Install the post-commit hook into any registered repository:

```sh
./scripts/install-hook.sh /path/to/your-repo
export CODEGRAPH_COMPOSE_DIR=/path/to/code-graph   # this checkout
export CODEGRAPH_REPO=your-repo                    # registered with --root /repos/your-repo
```

Each commit then incrementally ingests only the changed files
(`--trigger hook --enrich`), re-clusters only past the changed-edges
threshold, and never blocks the commit — failures land in
`.git/codegraph-hook.log`, and the hook exits immediately when the compose
stack isn't running. See `CLAUDE.md` for the rules assistants follow when
using the MCP server.

## Connecting Claude Code to the MCP server

The `mcp` service exposes the graph's query tools (`search_code`, `get_node`,
`get_neighbors`, `impact_of`, `kb_lookup`) over streamable HTTP on port 8765,
protected by a static bearer token (`MCP_BEARER_TOKEN` in `.env`). From the
host:

```sh
claude mcp add codegraph --transport http http://localhost:8765/mcp \
  --header "Authorization: Bearer $MCP_BEARER_TOKEN"
```

## Specs

The full technical specification and the slice-by-slice implementation plan live in
[`specs/`](specs/).
