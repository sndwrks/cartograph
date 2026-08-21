from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Host-run tools (alembic, the ingest/enrich CLIs) read the repo-root .env so
# nothing has to be exported by hand. Environment variables still win, which
# is how the compose services keep their derived DATABASE_URL; inside the
# image this path doesn't exist and is silently skipped.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application settings read from the environment, then the repo .env.

    Every field has a default so importing this module never crashes; services
    that actually need a value (db access, MCP auth) validate at use time.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://cartograph:change-me@db:5432/cartograph"
    ANTHROPIC_API_KEY: str = ""
    VOYAGE_API_KEY: str = ""
    MCP_BEARER_TOKEN: str = ""
    # clustering is skipped on incremental runs that changed fewer edges than
    # this, so community labels stay stable across small commits (slice 06)
    RECLUSTER_EDGE_THRESHOLD: int = 50
    # symbols spanning fewer lines than this aren't worth summary tokens (slice 13)
    SUMMARY_MIN_LINES: int = 3
    # Leiden leaves a long tail of single-node communities — 2517 of 2586 on a
    # 9k-node repo. They swamp the overview canvas and each would cost an LLM
    # call to "label" a cluster of one. Communities smaller than this are kept
    # in the graph but excluded from the overview and from labeling.
    COMMUNITY_MIN_SIZE: int = 2
    # in-flight LLM calls during enrichment. The summaries phase is otherwise
    # strictly sequential (~7s/node => ~17h for a 9k-node repo). Lower this if
    # the API starts returning 429s.
    ENRICH_CONCURRENCY: int = 12
    # LLM provider for the docs/summaries/communities phases: "anthropic" (API,
    # needs ANTHROPIC_API_KEY) or "claude-code" (local Claude Code CLI via the
    # Agent SDK, subscription auth, host-only). claude-code spawns one CLI
    # subprocess per concurrent call — consider ENRICH_CONCURRENCY=4 with it.
    ENRICH_PROVIDER: str = "anthropic"
    # nodes per commit: an interrupted run loses at most this much work
    ENRICH_COMMIT_EVERY: int = 100
    # Anthropic Message Batches mode (enrich --batch): the API caps a batch at
    # 100K requests or 256MB of payload. The byte bound is measured on the
    # serialized request JSON (ensure_ascii, an upper bound on what httpx
    # sends), and 64MB per chunk both stays far under the provider cap and
    # bounds submit's peak memory to one chunk of prompts.
    BATCH_MAX_REQUESTS: int = 100_000
    BATCH_MAX_BYTES: int = 64 * 1024 * 1024
    # seconds between polls while --batch --wait blocks on the provider;
    # most batches end within the hour, so a minute costs nothing
    BATCH_POLL_INTERVAL_S: float = 60.0
    # voyageai's AsyncClient defaults to max_retries=0, which disables the
    # tenacity backoff it already ships (429/503/timeout, exponential jitter
    # capped at 16s). Without this a single 429 kills a whole batch.
    EMBED_MAX_RETRIES: int = 5
    # seconds. The client defaults to no timeout at all, so one hung request
    # would stall the strictly-sequential embed loop forever.
    EMBED_TIMEOUT_S: float = 60.0
    # texts per Voyage request; voyage-code-3 caps a request at 1000 inputs
    EMBED_BATCH_SIZE: int = 128
    # estimated tokens per request, kept under voyage-code-3's 120K ceiling so
    # a handful of very long summaries can't push a full batch over it
    EMBED_MAX_TOKENS_PER_REQUEST: int = 100_000
    # seconds to wait between embed requests. 0 = no throttle, which is right
    # on standard rate limits. The keyless free tier allows 3 RPM / 10K TPM —
    # set this to 21 (and EMBED_MAX_TOKENS_PER_REQUEST to ~8000) to stay under
    # it, e.g. in the minutes after adding a payment method while the new
    # limits propagate.
    EMBED_MIN_INTERVAL_S: float = 0.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
