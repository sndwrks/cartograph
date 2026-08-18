# Cartograph

A self-hosted codebase knowledge graph. Cartograph ingests one or more repositories and
produces a persistent, queryable graph of code entities (files, classes, functions) and
their relationships (imports, calls, inheritance, references), enriched with vector
embeddings over LLM-written summaries. Humans explore the graph through a React SPA;
AI assistants query it through an MCP server backed by the same query layer.

## Quickstart

```sh
./scripts/up.sh         # dev stack, detached; creates .env from .env.example if missing
./scripts/down.sh       # stop and remove the containers (the graph survives)
```

- API: http://localhost:8000/api/v1/health
- Web: http://localhost:5173 (nginx, proxies `/api` to the API)
- MCP: http://localhost:8765
- The database publishes **no host port** in prod mode; all access goes through
  the API or MCP. Ad-hoc SQL: `docker compose exec db psql -U cartograph`.

`up.sh` edits nothing you've already written: it copies `.env.example` to `.env`
only when `.env` is absent, so **the first run brings the stack up with
placeholder credentials** — edit the passwords and keys and re-run it.

### Starting and stopping the stack

Both scripts `cd` to the repo root themselves, so they work from any directory.

| Command | What it does |
| --- | --- |
| `./scripts/up.sh` | **Dev mode (default)** — source mounts, hot reload, Vite dev server, Postgres published on `127.0.0.1:5433` for host-side tests |
| `./scripts/up.sh prod` | Plain compose stack: no dev override, no published database port |
| `./scripts/down.sh` | Stops and removes the containers. **The `pgdata` volume is kept** — everything you ingested is still there on the next `up.sh` |
| `./scripts/down.sh --wipe` | Also removes the volume, **destroying every ingested graph**. Prompts for confirmation first; anything but `y`/`yes` aborts |

`up.sh` always runs `--build -d`, so it doubles as the way to pick up code
changes — re-run it after editing a Dockerfile or dependency. It prints
`docker compose ps` and the three service URLs when it finishes.

Both scripts always pass the dev override to `docker compose down`, which is
what makes `down.sh` work regardless of which mode you started in.

## API keys and billing

Two of the four secrets in `.env` are third-party API keys, each billed by a
different vendor on its own dashboard. Both are **empty in `.env.example`** —
the graph ingests and browses without them; only the enrichment phases and
semantic search need them.

| `.env` variable | Needed by | Get the key at | Enter billing at |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | `docs`, `summaries`, `communities` — every LLM call | [Anthropic Console](https://platform.claude.com) → **API keys** | Console → **Plans & Billing** — buy prepaid credits or add a card |
| `VOYAGE_API_KEY` | `embeddings`, `kb`, and semantic search at query time | [Voyage dashboard](https://dashboard.voyageai.com) → **API keys** | Voyage dashboard → **Billing** — add a payment method |
| `MCP_BEARER_TOKEN` | the MCP server's bearer auth | you invent it (`openssl rand -hex 32`) | — nothing to pay |
| `POSTGRES_*` | the local database | you invent them | — nothing to pay |

**An Anthropic API key is not a Claude subscription.** Claude Pro/Max covers
claude.ai and Claude Code, not API calls — the Console is a separate account
surface with its own prepaid credit balance, and enrichment fails with a `401`
until that balance is funded. Summaries run on `claude-sonnet-5`
(`backend/src/cartograph/enrich/llm.py`), billed per input/output token at the
rate on Anthropic's [pricing page](https://platform.claude.com/docs/en/pricing);
embeddings run on `voyage-code-3` (`backend/src/cartograph/enrich/voyage.py`).
Cost scales with repository size and is charged only for what changed —
summaries are cached on content hashes, so the expensive run is the first one.
As an example here, an ~8,000 node, ~60,000 edge codebase cost ~$24 to generate
everything.

Voyage issues a **keyless free tier** (3 requests/min, 10K tokens/min) that the
embeddings phase will hit almost immediately on a real repository; see the
throttle settings under [the embeddings retry loop](#the-embeddings-retry-loop).
After adding a payment method the new limits take a few minutes to propagate,
during which the old ones still apply.

### Running without the keys

Nothing crashes at startup — the keys are validated at use time, and both CLI
entry points fail fast with a named error rather than a traceback
(`ANTHROPIC_API_KEY is not set — required for the summaries, communities, and
docs phases`). Concretely, without them:

- **Ingest, clustering, the SPA, and the graph-shaped MCP tools work fully** —
  `get_node`, `get_neighbors`, `impact_of`, `post_message`, `read_board` never
  touch either vendor.
- **`--enrich` and `python -m cartograph.enrich` exit immediately** on the first
  phase that needs the missing key.
- **`search_code` degrades rather than fails.** Search is text + semantic merged
  by reciprocal rank fusion; with no Voyage key the semantic half is skipped and
  the response is flagged `degraded`, leaving trigram name matching only. Good
  enough to find a symbol you can name, not enough to find one by description.
- **`kb_lookup` falls back** to non-semantic matching.

## Development

`./scripts/up.sh` already runs the dev override — backend source mounted for hot
reload, the Vite dev server, and Postgres published on `127.0.0.1:5433`
(loopback only) so host-side tests can reach it. The equivalent raw command is:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

DB-touching tests use a dedicated `cartograph_test` database created
automatically by the test suite. The whole stack doesn't need to be up for them
— just the database:

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
  uv run python -m cartograph.ingest register --name myrepo --root /repos/myrepo
docker compose run -v /host/path/myrepo:/repos/myrepo --rm api \
  uv run python -m cartograph.ingest run --repo myrepo
```

Every run writes an `ingest_runs` row with per-phase timings and node/edge deltas.

### Enriching after ingest: summaries, then embeddings

Ingest alone gives you structure — nodes and edges. Semantic search needs the
tier-3 enrichment phases, which are the only jobs that spend API money — they
need `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` and a funded balance on each
(see [API keys and billing](#api-keys-and-billing)).
`python -m cartograph.enrich` runs them; the order matters, because
`embeddings` embeds the text that `summaries` wrote:

```sh
# 1. summaries — reads source files, so the repo MUST still be mounted
docker compose run -v /host/path/myrepo:/repos/myrepo --rm api \
  uv run python -m cartograph.enrich --repo myrepo --phase summaries

# 2. embeddings — reads summaries from the database; no mount needed
docker compose run --rm api \
  uv run python -m cartograph.enrich --repo myrepo --phase embeddings
```

`--phase all` runs `docs → summaries → embeddings → communities → kb` in that
order (docs first, so new doc/config nodes get summarized and embedded in the
same pass). `--limit N` caps items per phase, which is the cheap way to sanity
check a prompt before spending on a full repo.

Everything is cached on content hashes, so re-runs only pay for what changed.
Nodes shorter than `SUMMARY_MIN_LINES` (default 3) are skipped as not worth the
tokens, and `ENRICH_CONCURRENCY` (default 12) sets how many LLM calls are in
flight — lower it if Anthropic starts returning 429s.

**Exit codes matter here.** Phases count write-offs instead of raising, so a
process that exits 0 is not proof it did the work:

| code | meaning |
| ---- | ------- |
| 0 | clean — every item processed |
| 1 | the phase itself blew up (traceback printed) |
| 2 | unknown repository |
| 3 | finished, but wrote off failed items — **re-run to retry** |

### The embeddings retry loop

The embeddings phase commits per batch, and `nodes_needing_embedding` filters
on `embedding IS NULL`, so a re-run resumes exactly where the last one stopped
rather than starting over. That makes a rate-limited run safe to simply repeat
until it comes back clean. Guard the loop on exit code 3 so a real error (1 or
2) breaks out instead of spinning forever:

```sh
while :; do
  docker compose run --rm api \
    uv run python -m cartograph.enrich --repo myrepo --phase embeddings
  status=$?
  [ "$status" -eq 3 ] || break        # 0 = done, 1/2 = real failure
  echo "partial run — retrying in 60s"
  sleep 60
done
exit "$status"
```

The same shape works for `--phase summaries`, which also commits per window
(`ENRICH_COMMIT_EVERY`, default 100 nodes).

If you are on Voyage's keyless free tier (3 requests/min, 10K tokens/min), the
defaults will trip the limiter immediately. Set these in `.env` instead of
relying on the retry loop to grind through it:

```sh
EMBED_MIN_INTERVAL_S=21             # throttle between requests (0 = off)
EMBED_MAX_TOKENS_PER_REQUEST=8000   # default 100000
```

### Keeping the graph fresh with a git hook

Install the post-commit hook into any registered repository:

```sh
./scripts/install-hook.sh /path/to/your-repo
export CARTOGRAPH_COMPOSE_DIR=/path/to/code-graph   # this checkout
export CARTOGRAPH_REPO=your-repo                    # registered with --root /repos/your-repo
```

Put those exports in your shell profile — the hook runs in whatever environment
git hands it. `CARTOGRAPH_COMPOSE_DIR` defaults to `~/code-graph` and the hook
logs `compose dir missing` and exits 0 if that path is wrong, so a silent
no-op usually means this is unset. `CARTOGRAPH_REPO` defaults to the basename of
the repo's toplevel directory, which is already correct whenever you registered
the repo under its own directory name; the hook mounts the working tree at
`/repos/$CARTOGRAPH_REPO`, so that name must match the registered `--root`.

Each commit then incrementally ingests only the changed files
(`--trigger hook --enrich`), re-clusters only past the changed-edges
threshold, and never blocks the commit — failures land in
`.git/cartograph-hook.log`, and the hook exits immediately when the compose
stack isn't running. See `CLAUDE.md` for the rules assistants follow when
using the MCP server.

## Connecting Claude Code to the MCP server

The `mcp` service exposes the graph's query tools (`search_code`, `get_node`,
`get_neighbors`, `impact_of`, `kb_lookup`, `post_message`, `read_board`) over
streamable HTTP on port 8765.

### The bearer token

There is no OAuth and no per-repository credential. The middleware does a
constant-time compare of the whole `Authorization` header against
`Bearer $MCP_BEARER_TOKEN`, read from `.env`; `/healthz` is the only exempt
route, and the server refuses to start if the token is empty. Change it from
the `.env.example` placeholder before using it for anything real:

```sh
NEW=$(openssl rand -hex 32)
sed -i '' "s/^MCP_BEARER_TOKEN=.*/MCP_BEARER_TOKEN=$NEW/" .env   # GNU sed: -i
docker compose up -d --force-recreate mcp
```

Check it from the host — 401 without the header, a JSON-RPC result with it:

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8765/mcp
curl -s -X POST http://localhost:8765/mcp \
  -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

### Registering the server in a consumer repository

Claude Code expands `${VAR}` in `.mcp.json` from the environment of the process
that launches `claude`, which keeps the token out of the file. In the repo you
want to query:

```json
{
  "mcpServers": {
    "cartograph": {
      "type": "http",
      "url": "http://localhost:8765/mcp",
      "headers": { "Authorization": "Bearer ${CARTOGRAPH_MCP_TOKEN}" }
    }
  }
}
```

```sh
echo "export CARTOGRAPH_MCP_TOKEN=$NEW" >> ~/.zshrc   # then open a new shell
```

Settings-file `env` blocks (`.claude/settings.local.json`) do **not** feed this
expansion — `claude mcp list` reports `Missing environment variables:
CARTOGRAPH_MCP_TOKEN` unless the variable is exported in the shell. If you would
rather not manage an env var, skip `.mcp.json` and let Claude Code store the
literal token outside the repo in `~/.claude.json`:

```sh
claude mcp add cartograph --scope local --transport http http://localhost:8765/mcp \
  --header "Authorization: Bearer $MCP_BEARER_TOKEN"
```

A project-scoped `.mcp.json` needs approving on the first `claude` launch in
that directory — until then `claude mcp list` shows `⏸ Pending approval`.
Confirm the connection with `/mcp` inside the session.

### Tell the assistant which repository it is in

The graph holds several repositories and there is no server-side default: `repo`
is an optional argument on `search_code` and `get_node`, and `get_neighbors` and
`impact_of` resolve by qualified name with no repo filter at all. Without
instructions an assistant will happily return matches from an unrelated
codebase. Add a section to the consumer repo's `CLAUDE.md` saying to pass
`repo="<name>"` on every `search_code` and `get_node` call, and copy in the
house rules from this repo's [`CLAUDE.md`](CLAUDE.md) — `kb_lookup` before
guessing at acronyms, the `resolved > llm_inferred > name_match` trust ordering,
`read_board` before editing a symbol, `impact_of` before touching high fan-in
code. None of that travels with the MCP connection.

## Specs

The full technical specification and the slice-by-slice implementation plan live in
[`specs/`](specs/).
