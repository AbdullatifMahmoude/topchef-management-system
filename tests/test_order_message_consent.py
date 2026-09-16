from types import SimpleNamespace

import pytest

from app.modules.orders import consent
from app.core.enums import OrderSource


class FakeDb:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
async def test_explicit_initial_contact_permission_is_snapshotted_for_unknown_customer(monkeypatch):
    customer = SimpleNamespace(whatsapp_status="unknown")

    class FakeCustomerService:
        def __init__(self, _db, _redis):
            pass

        async def get_customer(self, _customer_id):
            return customer

    monkeypatch.setattr(consent, "CustomerService", FakeCustomerService)
    db = FakeDb()
    order = SimpleNamespace(customer_id=7, whatsapp_initial_contact_allowed=True, source=OrderSource.ONLINE)

    resolved = await consent.resolve_order_message_consent(db, None, order)

    assert resolved.whatsapp_initial_contact_allowed is True
    assert customer.whatsapp_status == "unknown"
    assert db.added == []


@pytest.mark.asyncio
async def test_enabled_customer_does_not_need_repeated_initial_permission(monkeypatch):
    customer = SimpleNamespace(whatsapp_status="enabled")

    class FakeCustomerService:
        def __init__(self, _db, _redis):
            pass

        async def get_customer(self, _customer_id):
            return customer

    monkeypatch.setattr(consent, "CustomerService", FakeCustomerService)
    order = SimpleNamespace(customer_id=7, whatsapp_initial_contact_allowed=False, source=OrderSource.CASHIER)

    resolved = await consent.resolve_order_message_consent(FakeDb(), None, order)

    assert resolved.whatsapp_initial_contact_allowed is True


@pytest.mark.asyncio
async def test_cashier_cannot_create_initial_whatsapp_permission(monkeypatch):
    customer = SimpleNamespace(whatsapp_status="unknown")

    class FakeCustomerService:
        def __init__(self, _db, _redis):
            pass

        async def get_customer(self, _customer_id):
            return customer

    monkeypatch.setattr(consent, "CustomerService", FakeCustomerService)
    order = SimpleNamespace(customer_id=7, whatsapp_initial_contact_allowed=True, source=OrderSource.CASHIER)

    resolved = await consent.resolve_order_message_consent(FakeDb(), None, order)

    assert resolved.whatsapp_initial_contact_allowed is False
