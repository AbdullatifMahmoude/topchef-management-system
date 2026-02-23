from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from sqlalchemy import create_engine

from app.core.config import settings

Base = declarative_base()

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool
)


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_sync_engine():
    # إزالة asyncpg و query string SSL من URL
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").split("?")[0]
    return create_engine(
        sync_url,
        connect_args={"sslmode":"require"}  # psycopg2 يفهم SSL
    )