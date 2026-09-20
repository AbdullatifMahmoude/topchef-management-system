import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import settings
from app.core.redis import RedisClient


@pytest.mark.asyncio
async def test_concurrent_connect_reuses_one_bounded_client(monkeypatch):
    backend = Mock()
    backend.ping = AsyncMock(return_value=True)
    backend.aclose = AsyncMock()
    factory = Mock(return_value=backend)
    monkeypatch.setattr("app.core.redis.redis.from_url", factory)

    client = RedisClient()
    results = await asyncio.gather(*(client.connect() for _ in range(20)))

    assert results == [backend] * 20
    factory.assert_called_once()
    assert factory.call_args.kwargs["max_connections"] == settings.REDIS_MAX_CONNECTIONS


@pytest.mark.asyncio
async def test_failed_connect_closes_candidate(monkeypatch):
    backend = Mock()
    backend.ping = AsyncMock(side_effect=OSError("dns unavailable"))
    backend.aclose = AsyncMock()
    monkeypatch.setattr("app.core.redis.redis.from_url", Mock(return_value=backend))

    client = RedisClient()

    assert await client.connect() is None
    backend.aclose.assert_awaited_once()
    assert client.backend_name == "none"
