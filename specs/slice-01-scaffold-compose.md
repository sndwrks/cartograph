# Slice 01 — Scaffold & Docker Compose stack

## Goal

The repository skeleton exists and `docker compose up` brings up all four services with green healthchecks: a Postgres 18 + pgvector database reachable only on the internal network, a FastAPI app answering `/api/v1/health`, an nginx web service proxying `/api` to the API, and a stub MCP service. No data model, no business logic — just the runnable spine every later slice plugs into.

## Depends on

Nothing. This is the first slice.

## Spec references

`initial-spec.md` §2 (stack), §2.1 (compose topology).

## Requirements

### 1. Repo root

1. `LICENSE` — MIT, copyright 2026 sndwrks.
2. `README.md` — one-paragraph project description, quickstart (`cp .env.example .env`, `docker compose up --build`), and a pointer to `specs/`.
3. `.gitignore` — must include `.env`, `__pycache__/`, `.venv/`, `node_modules/`, `web/dist/`, `.pytest_cache/`, `*.egg-info/`.
4. `.env.example` with every variable documented by comment:
   ```
   POSTGRES_USER=cartograph
   POSTGRES_PASSWORD=change-me
   POSTGRES_DB=cartograph
   DATABASE_URL=postgresql+asyncpg://cartograph:change-me@db:5432/cartograph
   ANTHROPIC_API_KEY=            # tier-3 summaries/labels (slice 13)
   VOYAGE_API_KEY=               # embeddings, voyage-code-3 (slice 13)
   MCP_BEARER_TOKEN=change-me    # static token required by the MCP server (slice 09)
   ```

### 2. Backend package

1. `backend/pyproject.toml`: package name `cartograph`, `requires-python = ">=3.14"`, src layout (`backend/src/cartograph/`). Dependencies for this slice: `fastapi`, `uvicorn[standard]`, `pydantic-settings`. Dev group: `pytest`, `pytest-asyncio`, `httpx`.
2. `uv lock` committed as `backend/uv.lock`.
3. `src/cartograph/config.py`: a `Settings` class (pydantic-settings) reading `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `MCP_BEARER_TOKEN` from the environment, with a module-level `get_settings()` (cached).
4. `src/cartograph/api/app.py`: FastAPI app factory `create_app()`; router mounted at `/api/v1`; single endpoint `GET /api/v1/health` returning `{"status": "ok"}`.
5. `backend/Dockerfile`: based on a Python 3.14 image, installs uv, `uv sync --frozen`, default command runs uvicorn on `0.0.0.0:8000`. One image serves api, mcp, and one-shot jobs (they differ only by command).
6. Startup command for the api service is a small shell entrypoint that runs `alembic upgrade head || true` then uvicorn. The `|| true` is temporary scaffolding: alembic does not exist until slice 02, and slice 02 removes the `|| true`.

### 3. Web placeholder

1. `web/` — Vite + React 19 + TypeScript app (`npm create vite@latest` shape), rendering a single page that fetches `/api/v1/health` and shows the status. Real SPA arrives in slice 10; keep this minimal but building.
2. `web/Dockerfile` — multi-stage: `node` stage runs `npm ci && npm run build`; final stage is `nginx:alpine` serving `dist/`, with `web/nginx.conf` proxying `location /api { proxy_pass http://api:8000; }`.

### 4. Compose topology

`docker-compose.yml` — four services, one default network, no other networks:

| service | image/build | ports | notes |
|---|---|---|---|
| `db` | `pgvector/pgvector:pg18` | **none published** | env from `.env`; named volume `pgdata:/var/lib/postgresql/data`; healthcheck `pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}` interval 5s |
| `api` | `backend/Dockerfile` | `8000:8000` | `depends_on: db: condition: service_healthy`; env from `.env`; healthcheck curl of `/api/v1/health` |
| `web` | `web/Dockerfile` | `5173:80` | `depends_on: api` |
| `mcp` | `backend/Dockerfile` | `8765:8765` | `depends_on: db: condition: service_healthy`; command is a stub for now: `python -m cartograph.mcp_server` where `mcp_server/__main__.py` just serves an HTTP 200 "mcp stub" on 8765 (stdlib `http.server` is fine). Slice 09 replaces it. |

`docker-compose.dev.yml` (override): mounts `backend/src` into api and mcp with `uvicorn --reload`; replaces the web service with the Vite dev server (`npm run dev -- --host`) publishing 5173, with Vite's proxy config forwarding `/api` to `http://api:8000`.

## Files

- `LICENSE`, `README.md`, `.gitignore`, `.env.example`
- `docker-compose.yml`, `docker-compose.dev.yml`
- `backend/Dockerfile`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/entrypoint.sh`
- `backend/src/cartograph/{__init__.py,config.py}`
- `backend/src/cartograph/api/{__init__.py,app.py}`
- `backend/src/cartograph/mcp_server/{__init__.py,__main__.py}` (stub)
- `backend/tests/test_health.py`
- `web/` (Vite scaffold), `web/Dockerfile`, `web/nginx.conf`

## Acceptance criteria

1. `cp .env.example .env && docker compose up --build -d` → `docker compose ps` shows db, api, web, mcp all running; db and api healthy.
2. `curl http://localhost:8000/api/v1/health` → `{"status":"ok"}`.
3. `curl http://localhost:5173/api/v1/health` → same body, proving the nginx proxy path (browser never talks to :8000 directly).
4. `docker compose port db 5432` prints nothing / errors — the db publishes no host port.
5. `cd backend && uv run pytest` passes (`test_health.py` uses httpx `ASGITransport` against `create_app()` — no containers needed).
6. `docker compose -f docker-compose.yml -f docker-compose.dev.yml up` also works, with source edits hot-reloading the api.

## Out of scope

- Any database tables, SQLAlchemy, or Alembic (slice 02).
- The real MCP server (slice 09) and real SPA (slice 10).
- Auth of any kind beyond leaving `MCP_BEARER_TOKEN` in the env contract.
