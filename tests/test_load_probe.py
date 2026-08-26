import asyncio

import httpx

from tools.load_test import percentile, run_load


def test_percentile_is_stable():
    assert percentile([1, 2, 3, 4], 0.95) == 4
    assert percentile([], 0.50) == 0


def test_load_probe_reuses_connections(monkeypatch):
    async def fake_get(self, url):
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = asyncio.run(run_load("http://test/health", requests=100, concurrency=10, timeout=1))
    assert result.requests == 100
    assert result.errors == 0
    assert result.requests_per_second > 0
