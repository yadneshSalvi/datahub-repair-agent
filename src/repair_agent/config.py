"""Application settings loaded from environment variables and the repository `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration shared by the CLI, integration layer, and later services."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    datahub_gms_url: str = "http://localhost:8081"
    datahub_frontend_url: str = "http://localhost:9002"
    datahub_gms_token: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-sol"
    pr_mode: str = Field(default="dry-run", validation_alias="REPAIR_AGENT_PR_MODE")
    github_repo: str = "yadneshSalvi/datahub-repair-agent"
    api_port: int = 8002
    warehouse_platform: str = "snowflake"
    dbt_platform: str = "dbt"
    env: str = "PROD"
    namespace_prefix: str = "shop_prod."
    repo_root: Path = REPO_ROOT
    mcp_server_version: str = "0.6.0"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide, cached application settings."""

    return Settings()
