from types import SimpleNamespace

import pytest

from app.modules.settings.whatsapp_webhook import record_delivery_status


class FakeDb:
    def __init__(self, row):
        self.row = row

    async def scalar(self, _query):
        return self.row


@pytest.mark.asyncio
async def test_delivery_status_updates_matching_outbox_row():
    row = SimpleNamespace(delivery_status="accepted", delivery_updated_at=None, delivery_error=None)
    changed = await record_delivery_status(
        FakeDb(row), {"id": "wamid.1", "status": "delivered", "timestamp": "1700000000"},
    )
    assert changed is True
    assert row.delivery_status == "delivered"
    assert row.delivery_updated_at is not None
    assert row.delivery_error is None


@pytest.mark.asyncio
async def test_delivery_status_does_not_regress_on_out_of_order_webhook():
    row = SimpleNamespace(delivery_status="read", delivery_updated_at=None, delivery_error=None)
    changed = await record_delivery_status(
        FakeDb(row), {"id": "wamid.1", "status": "delivered", "timestamp": "1700000000"},
    )
    assert changed is False
    assert row.delivery_status == "read"
