from types import SimpleNamespace

from app.modules.settings.whatsapp import build_order_message, normalize_whatsapp_phone, whatsapp_config_ready


def test_normalize_egyptian_whatsapp_numbers():
    assert normalize_whatsapp_phone("01012345678") == "201012345678"
    assert normalize_whatsapp_phone("+20 101 234 5678") == "201012345678"
    assert normalize_whatsapp_phone("123") is None


def test_build_created_order_message_contains_order_details():
    message = build_order_message(
        {
            "order_number": "42",
            "order_status": "confirmed",
            "items": [{"product_id": 7, "quantity": 2, "total_price": "120"}],
            "discount_amount": "10",
            "delivery_fee": "15",
            "total_amount": "125",
        },
        "created",
    )
    assert "#42" in message
    assert "تم تأكيد الطلب" in message
    assert "صنف 7 × 2" in message
    assert "125.00 ج.م" in message


def test_status_message_is_compact():
    message = build_order_message(
        {"order_number": "9", "order_status": "out_for_delivery", "total_amount": "80"},
        "status_changed",
    )
    assert "الطلب خرج للتوصيل" in message
    assert "تفاصيل الطلب" not in message


def test_whatsapp_features_require_complete_enabled_configuration():
    complete = SimpleNamespace(
        enabled=True, api_key_configured=True, phone_number_id="123",
        graph_api_version="v23.0", language_code="ar",
    )
    assert whatsapp_config_ready(complete, template_name="approved_template") is True
    complete.api_key_configured = False
    assert whatsapp_config_ready(complete, template_name="approved_template") is False
    complete.api_key_configured = True
    complete.enabled = False
    assert whatsapp_config_ready(complete, template_name="approved_template") is False
    complete.enabled = True
    assert whatsapp_config_ready(complete, template_name="") is False
