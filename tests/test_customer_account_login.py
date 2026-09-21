from types import SimpleNamespace

import pytest
from fastapi import Response

from app.core.exceptions import AuthenticationError
from app.modules.customer import account_router
from app.modules.customer.account_schemas import CustomerLoginRequest


class FakeDb:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_customer_login_uses_phone_and_pin(monkeypatch):
    customer = SimpleNamespace(id=17, pin_hash="stored")

    async def get_by_phone(_self, phone):
        assert phone == "01000000001"
        return customer

    async def create_session(_db, customer_id, device_name):
        assert customer_id == 17
        assert device_name == "Chrome"
        return "access-token", "refresh-token", object()

    monkeypatch.setattr(account_router.CustomerRepository, "get_by_phone", get_by_phone)
    monkeypatch.setattr(account_router, "verify_password", lambda pin, stored: (pin, stored) == ("1234", "stored"))
    monkeypatch.setattr(account_router, "create_device_session", create_session)
    db = FakeDb()
    response = Response()

    result = await account_router.login_customer(
        CustomerLoginRequest(identifier="01000000001", pin="1234", device_name="Chrome"),
        response,
        db,
    )

    assert result.access_token == "access-token"
    assert result.customer_id == 17
    assert db.committed is True
    assert "topchef_customer_refresh=refresh-token" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_customer_login_rejects_wrong_pin(monkeypatch):
    async def get_by_phone(_self, _phone):
        return SimpleNamespace(id=17, pin_hash="stored")

    monkeypatch.setattr(account_router.CustomerRepository, "get_by_phone", get_by_phone)
    monkeypatch.setattr(account_router, "verify_password", lambda _pin, _stored: False)

    with pytest.raises(AuthenticationError):
        await account_router.login_customer(
            CustomerLoginRequest(identifier="01000000001", pin="9999"),
            Response(),
            FakeDb(),
        )


@pytest.mark.asyncio
async def test_customer_login_accepts_email(monkeypatch):
    customer = SimpleNamespace(id=18, pin_hash="stored")

    async def get_by_email(_self, email):
        assert email == "customer@example.com"
        return customer

    async def create_session(_db, customer_id, _device_name):
        assert customer_id == 18
        return "access-token", "refresh-token", object()

    monkeypatch.setattr(account_router.CustomerRepository, "get_by_email", get_by_email)
    monkeypatch.setattr(account_router, "verify_password", lambda pin, stored: (pin, stored) == ("1234", "stored"))
    monkeypatch.setattr(account_router, "create_device_session", create_session)

    result = await account_router.login_customer(
        CustomerLoginRequest(identifier="Customer@Example.com", pin="1234"),
        Response(),
        FakeDb(),
    )

    assert result.customer_id == 18
