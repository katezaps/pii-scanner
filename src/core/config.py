"""Application configuration via Pydantic Settings.

Sources are layered with this precedence (highest first):
    1. Environment variables
    2. .env file
    3. Defaults defined here

Three settings classes exist:

- ``AppSettings`` — shared fields used by both web and CLI (OpenAI,
  concurrency, timeouts, env, log level).
- ``WebSettings`` — extends ``AppSettings`` with database, API host,
  and retention fields. Used by the FastAPI app and DB scripts.
- ``CLISettings`` — extends ``AppSettings`` with CLI-specific env file
  loading. No database or API fields required.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Shared settings for both web and CLI contexts."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OpenAI
    openai_api_key: SecretStr
    openai_model: str = "gpt-4o-mini"
    agent_timeout_seconds: int = Field(default=300, ge=10, le=600)

    # Browser
    page_timeout_seconds: int = Field(default=45, ge=5, le=300)

    @model_validator(mode="after")
    def _check_timeout_ordering(self):
        if self.page_timeout_seconds >= self.agent_timeout_seconds:
            raise ValueError(
                f"page_timeout_seconds ({self.page_timeout_seconds}) must be less than "
                f"agent_timeout_seconds ({self.agent_timeout_seconds})"
            )
        return self

    # Environment
    env: Literal["development", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class WebSettings(AppSettings):
    """Full settings for the FastAPI web application and DB scripts."""

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "pii_scanner"
    postgres_user: str = "pii_scanner"
    postgres_password: SecretStr

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Retention
    scan_retention_days: int = Field(default=30, ge=1, le=365)

    @field_validator("api_host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        # Refuse to bind to anything other than localhost interfaces unless
        # explicitly intended. Privacy tool — this is a safety rail, not UX.
        if v not in {"127.0.0.1", "localhost", "::1"}:
            import warnings

            warnings.warn(
                f"API_HOST is set to {v!r}, which is not localhost. "
                "This tool is designed for local use; binding externally "
                "exposes scan endpoints. Ensure this is intentional.",
                stacklevel=2,
            )
        return v

    @property
    def database_url(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.postgres_user,
                password=self.postgres_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def _cli_env_file() -> str:
    """Read the CLI env file path from pyproject.toml, default to .env.cli."""
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        return data.get("tool", {}).get("pii-scanner", {}).get("cli", {}).get("env_file", ".env.cli")
    except FileNotFoundError:
        return ".env.cli"


class CLISettings(AppSettings):
    """Settings for the CLI. Env file path configured in pyproject.toml."""

    model_config = SettingsConfigDict(
        env_file=_cli_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> WebSettings:
    """Cached settings accessor for use as a FastAPI dependency."""
    return WebSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_cli_settings() -> CLISettings:
    """Cached settings accessor for the CLI."""
    return CLISettings()  # type: ignore[call-arg]
