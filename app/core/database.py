from sqlalchemy import Enum as SA_Enum
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from app.core.config import settings

Base = declarative_base()

def DbEnum(enum_cls, **kwargs):
    kwargs.setdefault(
        "values_callable",
        lambda cls: [e.value.upper() for e in cls]
    )
    kwargs.setdefault("native_enum", True)

    if "name" not in kwargs:
        raise ValueError(
            f"DbEnum({enum_cls.__name__}) requires a PostgreSQL enum name"
        )

    return SA_Enum(
        enum_cls,
        **kwargs
    )
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
            except (ValueError, AttributeError):
                return value


def _is_sqlite_url(url: str) -> bool:
    return url.startswith(("sqlite+aiosqlite://", "sqlite:///"))


def _is_transaction_pooler_url(url: str) -> bool:
    """Return whether the database endpoint uses transaction pooling.

    Supabase exposes its transaction pooler on port 6543. Unlike session mode,
    a client connection must not retain session state between transactions.
    """
    return make_url(url).port == 6543


def _resolve_runtime_database_url(url: str) -> str:
    """Use Supabase transaction mode without replacing an integration secret.

    FastAPI Cloud's Supabase integration owns DATABASE_URL and may expose it
    read-only in session mode. The shared pooler's host and credentials are the
    same for transaction mode; only its port changes from 5432 to 6543.
    """
    parsed_url = make_url(url)
    hostname = (parsed_url.host or "").lower()
    if hostname.endswith(".pooler.supabase.com") and parsed_url.port == 5432:
        parsed_url = parsed_url.set(port=6543)
        return parsed_url.render_as_string(hide_password=False)
    return url


def _prepare_async_database_url(url: str) -> str:
    if not _is_transaction_pooler_url(url):
        return url

    # SQLAlchemy's asyncpg dialect maintains its own prepared-statement cache
    # in addition to asyncpg's cache. Supabase transaction mode supports
    # neither, so both layers must be disabled.
    prepared_url = make_url(url).update_query_dict(
        {"prepared_statement_cache_size": "0"}
    )
    return prepared_url.render_as_string(hide_password=False)


def _build_async_engine_kwargs(url: str) -> dict:
    kwargs = {
        "echo": False,
        "future": True,
    }

    if _is_sqlite_url(url):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    elif _is_transaction_pooler_url(url):
        # Supavisor owns pooling in transaction mode. NullPool prevents every
        # horizontally scaled API replica from reserving idle client sessions.
        kwargs.update(
            {
                "poolclass": NullPool,
                "connect_args": {"statement_cache_size": 0},
            }
        )
    else:
        kwargs.update(
            {
                "pool_pre_ping": True,
                "pool_recycle": 1800,
                # Supabase session-mode poolers commonly enforce a small global
                # client limit. Keep each API replica bounded so one process
                # cannot consume the entire database pool.
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
            }
        )

    return kwargs


def _to_sync_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1).split("?")[0]
    if url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return url


runtime_database_url = _resolve_runtime_database_url(settings.DATABASE_URL)
async_database_url = _prepare_async_database_url(runtime_database_url)
engine_kwargs = _build_async_engine_kwargs(runtime_database_url)
engine: AsyncEngine = create_async_engine(async_database_url, **engine_kwargs)

if _is_sqlite_url(settings.DATABASE_URL):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

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
        sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False, "timeout": 15})
        @event.listens_for(sync_engine, "connect")
        def set_sqlite_pragma_sync(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
        return sync_engine
    return create_engine(sync_url, connect_args={"sslmode": "require"})
