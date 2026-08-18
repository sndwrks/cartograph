FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# curl is needed by the compose healthcheck (slim ships without it)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Dependency layer first for build caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY entrypoint.sh ./entrypoint.sh
RUN uv sync --frozen && chmod +x entrypoint.sh

CMD ["uv", "run", "uvicorn", "cartograph.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
