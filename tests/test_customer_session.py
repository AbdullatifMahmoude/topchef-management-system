from types import SimpleNamespace

import pytest
from fastapi import Response

from app.core.exceptions import AuthenticationError
from app.modules.customer import account_router
from app.modules.customer.account_schemas import CustomerProfileUpdate


class FakeDb:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True

@pytest.mark.asyncio
async def test_customer_session_returns_basic_profile_in_one_request(monkeypatch):
    async def inspect(_db, raw_refresh):
        assert raw_refresh == "valid-refresh"
        return "access-token", SimpleNamespace(customer_id=17)

    async def get_basic(_self, customer_id):
        assert customer_id == 17
        return SimpleNamespace(
            id=17,
            name="عميل",
            phone_number="01000000001",
            email="customer@example.com",
        )

    monkeypatch.setattr(account_router, "inspect_device_session", inspect)
    monkeypatch.setattr(account_router.CustomerRepository, "get_basic_by_id", get_basic)
    db = FakeDb()
    response = Response()

    result = await account_router.customer_session(response, db, "valid-refresh")

    assert result.authenticated is True
    assert result.access_token == "access-token"
    assert result.customer.name == "عميل"
    assert db.committed is False
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_customer_session_is_quiet_for_guests():
    result = await account_router.customer_session(Response(), FakeDb(), None)

    assert result.authenticated is False
    assert result.access_token is None


@pytest.mark.asyncio
async def test_customer_session_clears_invalid_refresh_cookie(monkeypatch):
    async def inspect(_db, _raw_refresh):
        raise AuthenticationError("انتهت جلسة الجهاز")

    monkeypatch.setattr(account_router, "inspect_device_session", inspect)
    db = FakeDb()
    response = Response()

    result = await account_router.customer_session(response, db, "invalid-refresh")

    assert result.authenticated is False
    assert "topchef_customer_refresh=" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_basic_profile_update_changes_only_name(monkeypatch):
    customer = SimpleNamespace(
        id=17,
        name="الاسم القديم",
        phone_number="01000000001",
        email="customer@example.com",
    )

    async def get_basic(_self, customer_id):
        assert customer_id == 17
        return customer

    class FakeRedis:
        def __init__(self):
            self.deleted = []

        async def delete(self, key):
            self.deleted.append(key)

    monkeypatch.setattr(account_router.CustomerRepository, "get_basic_by_id", get_basic)
    db = FakeDb()
    redis = FakeRedis()

    result = await account_router.update_customer_basic_profile(
        CustomerProfileUpdate(name="الاسم الجديد"),
        {"customer_id": 17},
        db,
        redis,
    )

    assert result.name == "الاسم الجديد"
    assert result.phone_number == "01000000001"
    assert db.committed is True
    assert redis.deleted == ["customer_profile:17"]
