import inspect

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
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
