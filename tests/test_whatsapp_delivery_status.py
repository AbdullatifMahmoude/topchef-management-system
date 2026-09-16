from types import SimpleNamespace

import pytest

from app.modules.settings import whatsapp_webhook
from app.modules.settings.whatsapp_webhook import record_consent_reply, record_delivery_status


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [("ENABLE_ORDER_UPDATES", "enabled"), ("DISABLE_ORDER_UPDATES", "disabled")],
)
async def test_quick_reply_persists_customer_choice(monkeypatch, payload, expected):
    customer = SimpleNamespace(
        whatsapp_status="pending", whatsapp_consent_at=None,
        whatsapp_checked_at=None, whatsapp_failure_reason="old",
    )

    class FakeRepository:
        def __init__(self, _db):
            pass

        async def get_by_phone(self, phone):
            assert phone == "201000000001"
            return customer

    monkeypatch.setattr(whatsapp_webhook, "CustomerRepository", FakeRepository)
    changed = await record_consent_reply(
        object(), {
            "from": "201000000001", "type": "button",
            "button": {"payload": payload, "text": "choice"},
        },
    )
    assert changed is True
    assert customer.whatsapp_status == expected
    assert customer.whatsapp_consent_at is not None
    assert customer.whatsapp_failure_reason is None
