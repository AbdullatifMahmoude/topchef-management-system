import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.core.logging import make_json_formatter
from app.core.security import create_access_token


def test_logs_distinguish_cairo_repeated_hour_in_utc():
    formatter = make_json_formatter()
    outputs = []
    for instant in (datetime(2026, 10, 29, 20, 30, tzinfo=UTC),
                    datetime(2026, 10, 29, 21, 30, tzinfo=UTC)):
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "test", (), None)
        record.created = instant.timestamp()
        outputs.append(json.loads(formatter.format(record))["timestamp"])
    assert outputs == ["2026-10-29T20:30:00Z", "2026-10-29T21:30:00Z"]


@pytest.mark.parametrize("instant", [datetime(2026, 10, 29, 20, 30, tzinfo=UTC),
                                    datetime(2026, 10, 29, 21, 30, tzinfo=UTC)])
def test_jwt_lifetime_uses_elapsed_utc_time_during_repeated_hour(monkeypatch, instant):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr("app.core.security.datetime", FixedDateTime)
    token = create_access_token({"sub": "cashier", "user_id": 1, "role": "cashier"}, timedelta(hours=2))
    assert jwt.get_unverified_claims(token)["exp"] == int((instant + timedelta(hours=2)).timestamp())


def test_jwt_validation_across_repeated_hour_expires_after_real_duration(monkeypatch):
    from app.core.security import decode_token

    clock = [datetime(2026, 10, 29, 20, 30, tzinfo=UTC)]

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr("app.core.security.datetime", FixedDateTime)
    token = create_access_token({"sub": "cashier", "user_id": 1, "role": "cashier"}, timedelta(hours=1))
    monkeypatch.setattr("jose.jwt.datetime", FixedDateTime)
    clock[0] += timedelta(minutes=59)
    assert decode_token(token) is not None
    clock[0] += timedelta(minutes=2)
    assert decode_token(token) is None
