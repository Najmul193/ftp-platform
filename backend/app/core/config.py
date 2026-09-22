"""Application settings, all overridable by environment variable.

Nothing here carries a production secret as a default. `SECRET_KEY` has a
development-only value that the application refuses to start with when
`ENVIRONMENT` is production.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    APP_NAME: str = "FTP Platform"
    API_V1_PREFIX: str = "/api/v1"

    # --- database --------------------------------------------------------- #
    DATABASE_URL: str = "postgresql+psycopg://ftp:ftp_dev@localhost:55432/ftp"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False
    #: Kills a runaway query rather than letting it occupy a connection.
    DB_STATEMENT_TIMEOUT_MS: int = 30_000

    # --- security --------------------------------------------------------- #
    SECRET_KEY: str = "dev-only-insecure-key-change-me"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_HOURS: int = 8
    #: Gate the application until a seeded password is replaced. Off while the
    #: platform is in development so it does not sit in the way; turn it on for
    #: any real deployment, where a shared initial password is a live exposure.
    ENFORCE_PASSWORD_CHANGE: bool = False
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    PASSWORD_MIN_LENGTH: int = 12

    # --- ingestion -------------------------------------------------------- #
    UPLOAD_MAX_BYTES: int = 100 * 1024 * 1024
    UPLOAD_STORAGE_DIR: str = "./var/uploads"
    INGEST_CHUNK_SIZE: int = 50_000

    # --- CORS -------------------------------------------------------------- #
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_dev_secret_in_production(cls, v: str, info) -> str:
        env = (info.data or {}).get("ENVIRONMENT", "development")
        if env == "production" and v.startswith("dev-only"):
            raise ValueError(
                "SECRET_KEY must be set explicitly when ENVIRONMENT=production"
            )
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
