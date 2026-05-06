from sqlalchemy import create_engine, TypeDecorator, Enum as SA_Enum
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.core.config import settings

Base = declarative_base()

class DbEnum(TypeDecorator):
    """
    Handles conversion between lowercase Python enums and uppercase DB enums.
    Usage: Column(DbEnum(MyEnum, name="my_enum_name"))
    """
    impl = SA_Enum
    cache_ok = True

    def __init__(self, enum_cls, **kwargs):
        self.enum_cls = enum_cls
        # Tell SQLAlchemy that the database values are uppercase
        if 'values_callable' not in kwargs:
            kwargs['values_callable'] = lambda cls: [e.value.upper() for e in cls]
        # Ensure name is passed for PostgreSQL native enum support
        super().__init__(enum_cls, **kwargs)

    def result_processor(self, dialect, coltype):
        # Bypass SA_Enum.result_processor because it raises LookupError if the DB
        # value doesn't exactly match the uppercase values in _object_lookup.
        # SQLite offline DB might return lowercase strings.
        import sqlalchemy
        string_processor = sqlalchemy.String().result_processor(dialect, coltype)

        def process(value):
            if string_processor and value is not None:
                value = string_processor(value)
            return self.process_result_value(value, dialect)

        return process

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value.upper()
        if isinstance(value, str):
            return value.upper()
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # value comes from DB as uppercase string
        try:
            # Since our enums are CaseInsensitiveEnum, this will work
            return self.enum_cls(value)
        except (ValueError, AttributeError):
            # Fallback to direct lowercase lookup if needed
            try:
                return self.enum_cls(value.lower())
            except:
                return value


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
            if session.in_transaction():
                await session.commit()
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_engine():
    sync_url = _to_sync_database_url(settings.DATABASE_URL)
    if sync_url.startswith("sqlite:///"):
        return create_engine(sync_url, connect_args={"check_same_thread": False})
    return create_engine(sync_url, connect_args={"sslmode": "require"})
