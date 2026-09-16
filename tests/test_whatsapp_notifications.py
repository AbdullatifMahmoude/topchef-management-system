from types import SimpleNamespace
import json

import httpx
import pytest

from app.modules.orders.schemas import OrderCreate
from app.modules.settings.whatsapp import (
    build_order_message,
    normalize_whatsapp_phone,
    order_template_parameters,
    send_template_message,
    send_template_text,
    whatsapp_config_ready,
)


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
    assert "رقم الطلب: 42" in message
    assert "#42" not in message
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


def test_approved_templates_receive_exact_parameter_counts_without_hash_prefix():
    order = {
        "order_number": "105", "order_status": "confirmed", "order_type": "delivery",
        "items": [{"product_name": "برجر لحم", "quantity": 2, "total_price": "240"}],
        "subtotal": "280", "discount_amount": "0", "delivery_fee": "25",
        "total_amount": "305", "payment_method": "cash",
        "customer_address": "15 شارع مصطفى النحاس", "customer_notes": "بدون بصل",
    }
    first = order_template_parameters(order, "created", first_order=True)
    created = order_template_parameters(order, "created")
    updated = order_template_parameters(order, "updated")
    status = order_template_parameters(order, "status_changed")
    assert len(first) == 11
    assert len(created) == 12
    assert len(updated) == 12
    assert len(status) == 3
    assert first[0] == created[1] == status[0] == "105"
    assert all("#105" not in value for value in first + created + updated + status)
    assert created[0] == "تم استلام طلب جديد"
    assert updated[0] == "تم تعديل تفاصيل الطلب"


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


def test_order_consent_defaults_to_unspecified_and_accepts_explicit_choice():
    base = {
        "items": [{"product_id": 1, "quantity": 1, "unit_price": "10"}],
        "order_type": "takeaway", "source": "cashier",
    }
    assert OrderCreate.model_validate(base).whatsapp_initial_contact_allowed is False
    assert OrderCreate.model_validate({**base, "whatsapp_initial_contact_allowed": True}).whatsapp_initial_contact_allowed is True


@pytest.mark.asyncio
async def test_template_send_returns_meta_message_id():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert '"name":"approved_template"' in request.content.decode()
        return httpx.Response(200, json={"messages": [{"id": "wamid.123"}]})

    config = SimpleNamespace(
        enabled=True, api_key_configured=True, phone_number_id="123",
        graph_api_version="v23.0", language_code="ar",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_template_text(
            "01012345678", "تحديث الطلب", "approved_template",
            config=config, token="secret", client=client,
        )
    assert result.accepted is True
    assert result.message_id == "wamid.123"


@pytest.mark.asyncio
async def test_first_order_template_sends_body_values_and_quick_reply_payloads():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.first"}]})

    config = SimpleNamespace(
        enabled=True, api_key_configured=True, phone_number_id="123",
        graph_api_version="v23.0", language_code="ar",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_template_message(
            "01012345678", ["105", "تم استلام الطلب"], "topchef_first_order_details",
            button_payloads=["ENABLE_ORDER_UPDATES", "DISABLE_ORDER_UPDATES"],
            config=config, token="secret", client=client,
        )
    assert result.accepted is True
    components = captured["template"]["components"]
    assert [component["type"] for component in components] == ["body", "button", "button"]
    assert components[1]["parameters"][0]["payload"] == "ENABLE_ORDER_UPDATES"
    assert components[2]["parameters"][0]["payload"] == "DISABLE_ORDER_UPDATES"
