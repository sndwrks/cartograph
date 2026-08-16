#!/bin/sh
# Tear down the CodeGraph stack.
#
#   ./scripts/down.sh          stop and remove containers (data volume kept)
#   ./scripts/down.sh --wipe   also remove the pgdata volume — DESTROYS the graph
set -e

cd "$(dirname "$0")/.."

if [ "${1:-}" = "--wipe" ]; then
    printf "this deletes the pgdata volume and every ingested graph — continue? [y/N] "
    read -r answer
    case "$answer" in
        y|Y|yes|YES) docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v ;;
        *) echo "aborted"; exit 1 ;;
    esac
else
    docker compose -f docker-compose.yml -f docker-compose.dev.yml down
fi
