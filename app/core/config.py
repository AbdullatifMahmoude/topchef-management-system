import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Top chef restaurant management system"
    VERSION: str = "0.0.1"
    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = Field(default=3, ge=1, le=10)
    DB_MAX_OVERFLOW: int = Field(default=2, ge=0, le=10)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=60)
    SECRET_KEY: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    REDIS_URL: str | None = None
    REMOTE_API: str = "https://topchef-system.fastapicloud.dev"
    TERMINAL_ID: str = Field(default=os.getenv("TERMINAL_ID", "T1"))
    CORS_ORIGINS: str = "http://127.0.0.1:5500,http://localhost:5500,https://topchef-dashboard.vercel.app,https://topchefeg.com,https://www.topchefeg.com"

    @property
    def cors_origins(self) -> list[str]:
        # Production may override CORS_ORIGINS completely. Keep the official
        # customer-facing origins trusted even when an older environment value
        # is still configured on the hosting provider.
        required_origins = (
            "https://topchefeg.com",
            "https://www.topchefeg.com",
        )
        configured = (
            origin.strip().rstrip("/")
            for origin in self.CORS_ORIGINS.split(",")
        )
        return list(dict.fromkeys(
            origin
            for origin in (*configured, *required_origins)
            if origin and origin != "*"
        ))

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def resolve_database_url(cls, value: str | None) -> str:
        if value:
            return value
        raise ValueError("DATABASE_URL is required")

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
        raise ValueError("SECRET_KEY is required")

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
