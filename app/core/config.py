from pydantic_settings import BaseSettings
from functools import lru_cache
import os
import asyncpg

class Settings(BaseSettings):
    PROJECT_NAME: str = "Top chef restaurant management system"
    VERSION: str = "0.0.1"

    # Loaded from Environment Variables
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    REDIS_URL: str

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"  # Allow extra env vars in .env without error
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
