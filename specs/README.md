# Cartograph — Implementation Slices

This folder decomposes [`initial-spec.md`](initial-spec.md) into 14 implementation slices, each sized for a single focused implementation session. Implement them in numeric order unless the dependency notes say otherwise; every slice's **Acceptance criteria** must pass before starting the next.

## How to work a slice

1. Read this README (layout + conventions), then read your slice file top to bottom.
2. Each slice restates everything it needs — open `initial-spec.md` only when the slice's *Spec references* section tells you to.
3. Do not implement anything listed under *Out of scope*, even if it seems adjacent — a later slice owns it.
4. Finish by running the acceptance criteria exactly as written.

## Slice index

| Slice | Title | Milestone | Depends on |
|---|---|---|---|
| [01](slice-01-scaffold-compose.md) | Scaffold & Docker Compose stack | M1 | — |
| [02](slice-02-data-model-migrations.md) | Data model & Alembic migrations | M1 | 01 |
| [03](slice-03-python-extractor.md) | Tier-1 Python extractor | M1 | 01 |
| [04](slice-04-typescript-extractor.md) | Tier-1 TypeScript/JS extractor | M1 | 03 |
| [05](slice-05-ingest-cli.md) | Ingest CLI & loader | M1 | 02, 03 (04 optional) |
| [06](slice-06-metrics-clustering.md) | Metrics & Leiden clustering job | M2 | 05 |
| [07](slice-07-query-layer-read-api.md) | Query layer & graph read API | M2 | 06 |
| [08](slice-08-kb-agents-messages-api.md) | KB, agents, messages, runs API | M2 | 02 (07 for router wiring) |
| [09](slice-09-mcp-server.md) | MCP server (query tools) | M2 | 07, 08 |
| [10](slice-10-spa-shell-overview.md) | SPA shell & overview view | M3 | 07 |
| [11](slice-11-spa-drillin-ego-search.md) | SPA drill-in, ego view, search palette | M3 | 10 |
| [12](slice-12-spa-side-panel.md) | SPA side panel | M3 | 11 |
| [13](slice-13-tier3-enrichment.md) | Tier-3 enrichment & hybrid search | M4 | 07, 08 |
| [14](slice-14-agent-board-incrementals.md) | Agent message board via MCP + git-hook incrementals | M5 | 09, 12, 13 |

Slices 03/04 are DB-free and can be built in parallel with 02. Slices 10–12 (SPA) can proceed in parallel with 08/09 once 07 is done.

## Repository layout (established by slice 01)

```
code-graph/
├── LICENSE                    # MIT
├── README.md
├── docker-compose.yml         # db, api, web, mcp
├── docker-compose.dev.yml     # dev override: source mounts, hot reload, Vite dev server
├── .env.example               # POSTGRES_PASSWORD, ANTHROPIC_API_KEY, VOYAGE_API_KEY, MCP_BEARER_TOKEN
├── .gitignore                 # includes .env
├── scripts/                   # post-commit hook template (slice 14)
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml         # uv-managed, Python 3.14, package `cartograph`
│   ├── uv.lock
│   ├── alembic.ini
│   ├── alembic/
│   ├── src/cartograph/
│   │   ├── config.py          # settings from env (pydantic-settings)
│   │   ├── models.py          # SQLAlchemy 2.0 models (slice 02)
│   │   ├── db.py              # async engine / session factory
│   │   ├── query/             # shared query layer — the ONLY place SQL lives
│   │   ├── extractors/        # base.py, resolve.py, python.py, typescript.py
│   │   ├── ingest/            # CLI: python -m cartograph.ingest
│   │   ├── metrics/           # CLI: python -m cartograph.metrics
│   │   ├── enrich/            # CLI: python -m cartograph.enrich (tier 3)
│   │   ├── api/               # FastAPI app + routers
│   │   └── mcp_server/        # MCP entrypoint, imports query/
│   └── tests/
└── web/                       # Vite + React 19 SPA
    ├── Dockerfile             # multi-stage: build → nginx
    └── src/
```

## Global conventions

- **Python 3.14, uv-managed.** All backend deps in one `backend/pyproject.toml`; pin via `uv.lock`. Run tools with `uv run <cmd>`.
- **Async everywhere in the backend.** SQLAlchemy 2.0 async (`asyncpg` driver), fully typed declarative models, FastAPI async endpoints.
- **SQL lives only in `cartograph/query/`.** API routers and MCP tools are thin wrappers over the same query functions. If a slice needs a new query, it adds a function there.
- **Confidence is sacred.** Every edge carries `resolved` | `llm_inferred` | `name_match`, and every API/MCP response that returns edges includes the tag. Trust ordering: `resolved` > `llm_inferred` > `name_match`.
- **`EMBED_DIM = 1024`** (Voyage `voyage-code-3`). Defined once in `models.py`; never hardcode 1024 elsewhere.
- **The db service never publishes a port.** All access goes through the API or MCP. Ad-hoc SQL: `docker compose exec db psql -U cartograph`.
- **Secrets** come from `.env` (gitignored). `.env.example` documents every variable; never commit real values.
- **Tests** use pytest (+ pytest-asyncio). DB-touching tests run against the compose `db` service via a test database, or a throwaway pgvector container; extractor tests (slices 03/04) are pure and need no DB.
- **Batch jobs are CLI modules**, not long-lived workers: `docker compose run api uv run python -m cartograph.<job> ...`.

## Milestone checkpoints

- **M1 (slices 01–05):** stack up, migrations applied, both tier-1 extractors, ingest CLI loads a real repo into nodes/edges.
- **M2 (06–09):** metrics + clustering, read API + text search, MCP server usable from Claude Code.
- **M3 (10–12):** SPA overview, drill-in, ego, Cmd+K search, side panel.
- **M4 (13):** tier-3 summaries/embeddings/community labels; hybrid search on.
- **M5 (14):** agent message board end to end, git-hook incremental ingestion.
