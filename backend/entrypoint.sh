#!/bin/sh
set -e

# With args (docker compose run api <cmd>): exec the command directly.
# Without args (service start): migrate, then serve.
if [ $# -gt 0 ]; then
    exec "$@"
fi

uv run alembic upgrade head

exec uv run uvicorn codegraph.api.app:app --host 0.0.0.0 --port 8000
