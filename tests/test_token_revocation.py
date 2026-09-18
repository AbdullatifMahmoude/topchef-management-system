import asyncio

from app.core.token_blacklist import TokenBlacklist


def test_revocation_check_fails_closed_when_backend_is_missing(monkeypatch):
    async def unavailable():
        return None

    monkeypatch.setattr("app.core.token_blacklist.redis_client.connect", unavailable)
    assert asyncio.run(TokenBlacklist().is_revoked("token")) is None
