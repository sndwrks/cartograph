from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings read from the environment.

    Every field has a default so importing this module never crashes; services
    that actually need a value (db access, MCP auth) validate at use time.
    """

    model_config = SettingsConfigDict(extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://codegraph:change-me@db:5432/codegraph"
    ANTHROPIC_API_KEY: str = ""
    VOYAGE_API_KEY: str = ""
    MCP_BEARER_TOKEN: str = ""
    # clustering is skipped on incremental runs that changed fewer edges than
    # this, so community labels stay stable across small commits (slice 06)
    RECLUSTER_EDGE_THRESHOLD: int = 50
    # symbols spanning fewer lines than this aren't worth summary tokens (slice 13)
    SUMMARY_MIN_LINES: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
