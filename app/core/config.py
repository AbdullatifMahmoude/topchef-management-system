from pydantic_settings import BaseSettings
from pydantic import field_validator

from functools import lru_cache
import os


class Settings(BaseSettings):
    PROJECT_NAME: str = "Top chef restaurant management system"
    VERSION: str = "0.0.1"

    # Loaded from Environment Variables
    DATABASE_URL: str

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def assemble_db_url(cls, v: str) -> str:
        if v and v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        # asyncpg uses 'ssl=' instead of 'sslmode='
        if v and "sslmode=" in v:
            v = v.replace("sslmode=", "ssl=")
            
        return v


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
