import asyncio
import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import (
    _build_async_engine_kwargs,
    _is_transaction_pooler_url,
    _prepare_async_database_url,
    _resolve_runtime_database_url,
    engine,
)
from app.main import app, collect_health, lifespan


class AsyncContext:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self.value

    async def __aexit__(self, *_):
        return False


class FakeConnection:
    async def execute(self, statement):
        assert str(statement) == "SELECT 1"


class FakeEngine:
    def __init__(self, error=None):
        self.error = error

    def connect(self):
        return AsyncContext(FakeConnection(), self.error)


class FakeCache:
    redis = None
    status_label = "disconnected"


def test_cors_never_allows_wildcard_with_credentials():
    assert "*" not in settings.cors_origins


@pytest.mark.parametrize(
    "origin",
    ["https://topchefeg.com", "https://www.topchefeg.com"],
)
def test_cors_allows_customer_website(origin):
    response = TestClient(app).options(
        "/menu/products",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.asyncio
async def test_health_checks_database_and_allows_redis_degraded_mode():
    status, payload = await collect_health(FakeEngine(), FakeCache())
    assert status == 200
    assert payload == {"status": "degraded", "database": "connected", "redis": "disconnected"}


@pytest.mark.asyncio
async def test_health_is_unhealthy_when_database_query_fails():
    status, payload = await collect_health(FakeEngine(RuntimeError("down")), FakeCache())
    assert status == 503
    assert payload["database"] == "disconnected"


def test_startup_contains_no_schema_mutation_sql():
    source = inspect.getsource(lifespan).upper()
    for statement in ("ALTER TABLE", "CREATE TABLE", "DROP CONSTRAINT", "CREATE TYPE"):
        assert statement not in source


def test_database_pool_is_bounded_below_provider_session_limit():
    assert settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW <= 5
    runtime_url = _resolve_runtime_database_url(settings.DATABASE_URL)
    if _is_transaction_pooler_url(runtime_url):
        assert isinstance(engine.pool, NullPool)
    else:
        assert engine.pool.size() == settings.DB_POOL_SIZE


def test_supabase_transaction_pooler_disables_both_asyncpg_caches():
    url = (
        "postgresql+asyncpg://postgres.project:secret@"
        "aws-0-region.pooler.supabase.com:6543/postgres?ssl=require"
    )

    prepared_url = _prepare_async_database_url(url)
    kwargs = _build_async_engine_kwargs(url)

    assert _is_transaction_pooler_url(url)
    assert "postgres.project:secret@" in prepared_url
    assert ":***@" not in prepared_url
    assert "prepared_statement_cache_size=0" in prepared_url
    assert "ssl=require" in prepared_url
    assert kwargs["poolclass"] is NullPool
    assert kwargs["connect_args"] == {"statement_cache_size": 0}
    assert "pool_size" not in kwargs


def test_managed_supabase_session_url_is_upgraded_without_losing_secret():
    managed_url = (
        "postgresql+asyncpg://postgres.project:p%40ssword@"
        "aws-0-region.pooler.supabase.com:5432/postgres?ssl=require"
    )

    runtime_url = _resolve_runtime_database_url(managed_url)

    assert "p%40ssword@" in runtime_url
    assert "pooler.supabase.com:6543/postgres" in runtime_url
    assert _is_transaction_pooler_url(runtime_url)


def test_non_supabase_database_url_is_not_rewritten():
    url = "postgresql+asyncpg://user:secret@database.internal:5432/app"

    assert _resolve_runtime_database_url(url) == url


def test_session_pooler_keeps_bounded_application_pool():
    url = (
        "postgresql+asyncpg://postgres.project:secret@"
        "aws-0-region.pooler.supabase.com:5432/postgres?ssl=require"
    )

    kwargs = _build_async_engine_kwargs(url)

    assert not _is_transaction_pooler_url(url)
    assert _prepare_async_database_url(url) == url
    assert kwargs["pool_size"] == settings.DB_POOL_SIZE
    assert kwargs["max_overflow"] == settings.DB_MAX_OVERFLOW
    assert "poolclass" not in kwargs


def test_whatsapp_worker_is_started_only_by_leader_election():
    source = inspect.getsource(lifespan)
    assert "if settings.WHATSAPP_OUTBOX_ENABLED and not settings.WHATSAPP_INTEGRATION_PAUSED:" in source
    assert "on_leader_elected(whatsapp_outbox_worker.start)" in source
    assert "on_leader_lost(whatsapp_outbox_worker.stop)" in source
    assert "await whatsapp_outbox_worker.start()" not in source


def test_private_websocket_does_not_materialize_order_snapshot():
    from app.modules.orders.router import websocket_orders

    source = inspect.getsource(websocket_orders)
    assert "page_size=500" not in source
    assert "ORDER_SNAPSHOT" not in source
    assert '"type": "CONNECTION_READY"' in source


def test_admin_dashboard_coalesces_parallel_initial_loads():
    source = Path("app/frontend/js/orders_dashboard.js").read_text(encoding="utf-8")
    assert "if (dashboardLoadPromise) return dashboardLoadPromise;" in source
    assert 'type === "ORDER_SNAPSHOT"' not in source


def test_cashier_reuses_authoritative_pricing_for_identical_previews():
    source = Path("app/frontend/cashier/js/cashier.js").read_text(encoding="utf-8")
    assert "_lastSuccessfulPricingBody === requestBody" in source
    assert "Date.now() - _lastSuccessfulPricingAt < 2000" in source
    assert "displayCashierPricing(_lastSuccessfulPricingData)" in source
    assert "generation !== _pricingGeneration" in source


def test_dashboard_order_query_avoids_unrendered_relationships():
    from app.modules.orders.repository import OrderRepository

    source = inspect.getsource(OrderRepository.list_dashboard_orders)
    assert "Order.items" in source
    for relationship in ("Order.creator", "Order.delivery_person", "Order.address", "Order.modifications"):
        assert relationship not in source


@pytest.mark.asyncio
async def test_leader_tasks_are_cancelled_when_leadership_is_lost():
    from app.core.leader import LeaderManager

    manager = LeaderManager("test-worker")
    started = asyncio.Event()

    async def long_running_task():
        started.set()
        await asyncio.sleep(3600)

    manager._start_leader_task(long_running_task)
    await started.wait()
    task = next(iter(manager._leader_tasks))

    await manager._cancel_leader_tasks()

    assert task.cancelled()
    assert not manager._leader_tasks
