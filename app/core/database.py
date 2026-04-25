from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.core.config import settings

Base = declarative_base()


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite+aiosqlite://") or url.startswith("sqlite:///")


def _to_sync_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1).split("?")[0]
    if url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return url


engine_kwargs = {
    "echo": False,
    "future": True,
}

if _is_sqlite_url(settings.DATABASE_URL):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "pool_size": 5,
            "max_overflow": 10,
        }
    )


engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_sync_engine():
    sync_url = _to_sync_database_url(settings.DATABASE_URL)
    if sync_url.startswith("sqlite:///"):
        return create_engine(sync_url, connect_args={"check_same_thread": False})
    return create_engine(sync_url, connect_args={"sslmode": "require"})
