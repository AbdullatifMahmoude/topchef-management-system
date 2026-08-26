import time

import pytest

from app.modules.auth.service import AuthService, _password_reset_requests
from app.modules.infrastructure.middlewares.auth import PUBLIC_PATHS


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        self.expirations[key] = seconds


def test_password_reset_endpoints_are_public():
    assert "/auth/forgot-password" in PUBLIC_PATHS
    assert "/auth/reset-password" in PUBLIC_PATHS


@pytest.mark.asyncio
async def test_password_reset_rate_limit_uses_shared_redis():
    redis = FakeRedis()
    service = AuthService(db=None, redis=redis)

    assert await service._allow_password_reset_request("Admin") is True
    assert await service._allow_password_reset_request("admin") is False
    assert list(redis.expirations.values()) == [60]
    assert all("admin" not in key for key in redis.values)


@pytest.mark.asyncio
async def test_password_reset_rate_limit_fallback_is_bounded():
    _password_reset_requests.clear()
    service = AuthService(db=None, redis=None)

    assert await service._allow_password_reset_request("cashier") is True
    assert await service._allow_password_reset_request("cashier") is False

    _password_reset_requests["expired"] = time.monotonic() - 61
    await service._allow_password_reset_request("another-user")
    assert "expired" not in _password_reset_requests
