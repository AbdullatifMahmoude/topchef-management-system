import pytest

import app.main  # noqa: F401 - registers all ORM models before mapper configuration
from app.modules.orders.notifications import AccountOrderNotifications


class RecordingSession:
    def __init__(self, existing=None):
        self.added = []
        self.existing = existing

    def add(self, value):
        self.added.append(value)

    async def scalar(self, _query):
        return self.existing


@pytest.mark.asyncio
async def test_registered_customer_receives_private_order_notification():
    db = RecordingSession()
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": 7, "order_number": "0042", "order_status": "confirmed"},
        "status_changed",
    )
    assert queued is True
    assert len(db.added) == 1
    assert db.added[0].customer_id == 7
    assert db.added[0].order_id == 12
    assert "0042" in db.added[0].message


@pytest.mark.asyncio
async def test_guest_order_does_not_create_account_notification():
    db = RecordingSession()
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": None, "order_number": "0042", "order_status": "new"},
        "created",
    )
    assert queued is False
    assert db.added == []


@pytest.mark.asyncio
async def test_non_status_edits_do_not_spam_customer():
    db = RecordingSession()
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": 7, "order_number": "0042", "order_status": "confirmed"},
        "updated",
    )
    assert queued is False
    assert db.added == []


@pytest.mark.asyncio
async def test_duplicate_status_event_is_idempotent():
    db = RecordingSession(existing=99)
    queued = await AccountOrderNotifications(db).enqueue(
        {"id": 12, "customer_id": 7, "order_number": "0042", "order_status": "confirmed"},
        "status_changed",
    )
    assert queued is False
    assert db.added == []
