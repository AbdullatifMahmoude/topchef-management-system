import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


def _runtime_mode() -> str:
    return os.getenv("RUNTIME_MODE", "cloud").strip().lower()


def _desktop_database_url() -> str:
    from desktop.config import DB_PATH

    return f"sqlite+aiosqlite:///{Path(DB_PATH).resolve().as_posix()}"


def _default_remote_api() -> str:
    if _runtime_mode() == "desktop":
        from desktop.config import config as desktop_config

        return desktop_config.server_url.rstrip("/")
    return "https://topchef-system.fastapicloud.dev"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Top chef restaurant management system"
    VERSION: str = "0.0.1"
    RUNTIME_MODE: str = Field(default_factory=_runtime_mode)
    DATABASE_URL: str | None = None
    SECRET_KEY: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    REDIS_URL: str | None = None
    REMOTE_API: str = Field(default_factory=_default_remote_api)
    TERMINAL_ID: str = Field(default=os.getenv("TERMINAL_ID", "T1"))

    @field_validator("RUNTIME_MODE", mode="before")
    @classmethod
    def normalize_runtime_mode(cls, value: str | None) -> str:
        return (value or "cloud").strip().lower()

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def resolve_database_url(cls, value: str | None) -> str:
        runtime_mode = _runtime_mode()
        if runtime_mode == "desktop":
            return _desktop_database_url()
        if value:
            return value
        raise ValueError("DATABASE_URL is required outside desktop mode")

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def assemble_db_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if "sslmode=" in value:
            value = value.replace("sslmode=", "ssl=")
        return value

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def resolve_secret_key(cls, value: str | None) -> str:
        if value:
            return value
        if _runtime_mode() == "desktop":
            return "topchef-desktop-local-secret"
        raise ValueError("SECRET_KEY is required outside desktop mode")

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def resolve_redis_url(cls, value: str | None) -> str:
        if value:
            return value
        return "redis://localhost:6379/0"

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore",
    }


def _resolve_env_file() -> str:
    """Find .env next to the EXE in frozen mode, or in project root in dev."""
    import sys
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / ".env"
        if candidate.exists():
            return str(candidate)
    return ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings(_env_file=_resolve_env_file())


settings = get_settings()
