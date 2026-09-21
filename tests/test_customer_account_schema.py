import pytest
from pydantic import ValidationError

from app.modules.customer.account_schemas import (
    CustomerCompleteRequest,
    CustomerProfile,
)


def test_customer_profile_exposes_whatsapp_status_to_checkout():
    profile = CustomerProfile(
        id=7,
        name="عميل",
        phone_number="01000000001",
        whatsapp_status="disabled",
        addresses=[],
    )

    assert profile.whatsapp_status == "disabled"


def test_customer_profile_defaults_unknown_whatsapp_status():
    profile = CustomerProfile(
        id=7,
        name="عميل",
        phone_number="01000000001",
        addresses=[],
    )

    assert profile.whatsapp_status == "unknown"


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
