from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions import AuthenticationServiceUnavailable


@pytest.mark.asyncio
async def test_logout_without_closing_shift_revokes_token(monkeypatch):
    auth = import_module("app.modules.auth.router")
    shifts = import_module("app.modules.shifts.service")
    revoke = AsyncMock(return_value=True)
    close = AsyncMock()
    monkeypatch.setattr(auth, "decode_token", lambda token: {"exp": 2000000000, "user_id": 7, "role": "cashier"})
    monkeypatch.setattr(auth.TokenBlacklist, "revoke_token", revoke)
    monkeypatch.setattr(shifts.ShiftsService, "end_shift", close)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

    result = await auth.logout(close_shift=False, credentials=credentials, _current_user=object(), redis=None)
    assert result["message"] == "Logged out successfully"
    revoke.assert_awaited_once_with("test-token", 2000000000)
    close.assert_not_awaited()

    revoke.return_value = False
    with pytest.raises(AuthenticationServiceUnavailable):
        await auth.logout(close_shift=False, credentials=credentials, _current_user=object(), redis=None)
    close.assert_not_awaited()
