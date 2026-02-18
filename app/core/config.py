from pydantic_settings import BaseSettings
from functools import lru_cache
import os
import asyncpg

class Settings(BaseSettings):
    PROJECT_NAME: str = "Top chef restaurant management system"
    VERSION: str = "0.0.1"

    DATABASE_URL: str = os.getenv(
        "database_url",
        "postgresql+asyncpg://postgres:parmagai@localhost:5432/parmagai"
    )

    SECRET_KEY: str = "a9f3d8c1b7e2f4a0c6d9e5b1c8f0a2d3e7f9a1b4c5d6e8f0a9b7c2d4e6f8"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720

    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
