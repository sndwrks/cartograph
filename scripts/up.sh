#!/bin/sh
# Bring up the CodeGraph stack.
#
#   ./scripts/up.sh        dev mode (default): source mounts + hot reload,
#                          Vite dev server, Postgres published on 127.0.0.1:5433
#                          so host-side pytest can reach it
#   ./scripts/up.sh prod   plain compose stack, no dev override, no db port
set -e

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "no .env found — creating one from .env.example; edit passwords/keys before exposing anything" >&2
    cp .env.example .env
fi

if [ "${1:-dev}" = "prod" ]; then
    docker compose up --build -d
else
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
fi

docker compose ps
echo
echo "API: http://localhost:8000/api/v1/health"
echo "Web: http://localhost:5173"
echo "MCP: http://localhost:8765"
