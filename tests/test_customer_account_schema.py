import pytest
from pydantic import ValidationError

from app.modules.customer.account_schemas import (
    CustomerCompleteRequest,
    CustomerBasicProfile,
    CustomerProfile,
    CustomerSessionResponse,
)


def test_customer_profile_contains_only_account_data():
    profile = CustomerProfile(
        id=7,
        name="عميل",
        phone_number="01000000001",
        addresses=[],
    )
    assert "whatsapp_status" not in profile.model_dump()


def test_customer_session_returns_only_basic_account_data():
    session = CustomerSessionResponse(
        authenticated=True,
        access_token="token",
        customer=CustomerBasicProfile(
            id=7,
            name="عميل",
            phone_number="01000000001",
            email="customer@example.com",
        ),
    )

    assert session.authenticated is True
    assert set(session.customer.model_dump()) == {
        "id", "name", "phone_number", "email",
    }


def test_guest_session_has_no_account_data_or_token():
    session = CustomerSessionResponse(authenticated=False)

    assert session.access_token is None
    assert session.customer is None


def test_activation_requires_matching_pin_confirmation():
    with pytest.raises(ValidationError, match="غير متطابقين"):
        CustomerCompleteRequest(
            email="customer@example.com",
            phone="01000000001",
            challenge_id="a" * 32,
            purpose="activate",
            pin="1234",
            pin_confirmation="5678",
            name="عميل",
        )


def test_customer_phone_input_rejects_more_than_twelve_characters():
    with pytest.raises(ValidationError, match="at most 12"):
        CustomerCompleteRequest(
            email="customer@example.com",
            phone="2010000000001",
            challenge_id="a" * 32,
            purpose="activate",
            pin="1234",
            pin_confirmation="1234",
            name="عميل",
        )
