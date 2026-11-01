from types import SimpleNamespace

import pytest

from app.core.exceptions import AccountAlreadyActiveError
from app.modules.customer import account_router
from app.modules.customer.account_schemas import (
    CustomerChallengeRequest,
    CustomerCompleteRequest,
)


class FakeDb:
    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.mark.asyncio
async def test_activation_of_existing_account_redirects_to_login(monkeypatch):
    customer = SimpleNamespace(id=9, pin_hash="stored-pin")

    async def get_by_phone(_self, phone):
        assert phone == "01000000001"
        return customer

    async def get_by_email(_self, _email):
        return None

    async def must_not_create_challenge(*_args, **_kwargs):
        raise AssertionError("An active account must not receive a new activation challenge")

    monkeypatch.setattr(account_router.CustomerRepository, "get_by_phone", get_by_phone)
    monkeypatch.setattr(account_router.CustomerRepository, "get_by_email", get_by_email)
    monkeypatch.setattr(account_router, "create_email_challenge", must_not_create_challenge)

    with pytest.raises(AccountAlreadyActiveError) as exc:
        await account_router.begin_challenge(
            CustomerChallengeRequest(
                phone="01000000001",
                email="customer@example.com",
                purpose="activate",
            ),
            object(),
            object(),
        )

    assert exc.value.error_code == "ACCOUNT_ALREADY_ACTIVE"


@pytest.mark.asyncio
async def test_unactivated_existing_phone_reuses_customer_record(monkeypatch):
    customer = SimpleNamespace(id=11, pin_hash=None, name="الاسم القديم")
    captured = {}

    async def get_by_phone(_self, _phone):
        return customer

    async def get_by_email(_self, _email):
        return None

    async def create_challenge(_redis, **kwargs):
        captured.update(kwargs)
        return {"challenge_id": "challenge", "expires_in": 600}

    monkeypatch.setattr(account_router.CustomerRepository, "get_by_phone", get_by_phone)
    monkeypatch.setattr(account_router.CustomerRepository, "get_by_email", get_by_email)
    monkeypatch.setattr(account_router, "create_email_challenge", create_challenge)

    result = await account_router.begin_challenge(
        CustomerChallengeRequest(
            phone="01000000001",
            email="customer@example.com",
            purpose="activate",
        ),
        object(),
        object(),
    )

    assert result["challenge_id"] == "challenge"
    assert captured["actor_id"] == customer.id


@pytest.mark.asyncio
async def test_activation_updates_existing_customer_name_instead_of_creating_duplicate(monkeypatch):
    customer = SimpleNamespace(
        id=11,
        pin_hash=None,
        name="الاسم القديم",
        email=None,
        phone_number="01000000001",
    )

    async def get_by_phone(_self, _phone):
        return customer

    async def get_by_email(_self, _email):
        return None

    async def consume(*_args, **_kwargs):
        return {
            "actor_id": customer.id,
            "phone": "01000000001",
            "email": "customer@example.com",
        }

    async def create_session(_db, customer_id, _device_name):
        assert customer_id == customer.id
        return "access", "refresh", object()

    monkeypatch.setattr(account_router.CustomerRepository, "get_by_phone", get_by_phone)
    monkeypatch.setattr(account_router.CustomerRepository, "get_by_email", get_by_email)
    monkeypatch.setattr(account_router, "consume_email_challenge", consume)
    monkeypatch.setattr(account_router, "create_device_session", create_session)
    monkeypatch.setattr(account_router, "get_password_hash", lambda pin: f"hashed:{pin}")

    result = await account_router.complete_customer_auth(
        CustomerCompleteRequest(
            phone="01000000001",
            email="customer@example.com",
            challenge_id="a" * 32,
            purpose="activate",
            pin="1234",
            pin_confirmation="1234",
            name="الاسم الجديد",
        ),
        account_router.Response(),
        FakeDb(),
        None,
    )

    assert result.customer_id == customer.id
    assert customer.name == "الاسم الجديد"
    assert customer.email == "customer@example.com"
    assert customer.pin_hash == "hashed:1234"
