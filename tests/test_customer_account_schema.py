from app.modules.customer.account_schemas import CustomerProfile


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
