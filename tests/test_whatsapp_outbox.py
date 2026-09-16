from datetime import timedelta

import pytest

from app.modules.settings.whatsapp_outbox import (
    enqueue_order_notification,
    order_event_key,
    order_message_plan,
    order_template_name,
    retry_delay,
)


def test_order_outbox_key_is_idempotent_for_same_event():
    order = {"id": 7, "order_number": "A-7", "order_status": "confirmed", "total_amount": "50.00"}
    assert order_event_key(order, "created") == order_event_key(dict(order), "created")


def test_order_outbox_key_changes_for_update_or_payload_change():
    order = {"id": 7, "order_status": "confirmed"}
    changed = {"id": 7, "order_status": "completed"}
    assert order_event_key(order, "created") != order_event_key(order, "updated")
    assert order_event_key(order, "updated") != order_event_key(changed, "updated")


@pytest.mark.asyncio
async def test_order_without_explicit_whatsapp_consent_is_not_queued():
    assert await enqueue_order_notification(object(), {"customer_phone": "01000000001"}, "created") is False


def test_outbox_retry_uses_bounded_exponential_backoff():
    assert retry_delay(1) == timedelta(seconds=2)
    assert retry_delay(4) == timedelta(seconds=16)
    assert retry_delay(20) == timedelta(seconds=300)


def test_order_events_use_the_approved_two_template_contract():
    config = type("Config", (), {
        "order_details_template_name": "topchef_order_details",
        "order_status_template_name": "topchef_order_status",
    })()
    assert order_template_name(config, "created") == "topchef_order_details"
    assert order_template_name(config, "updated") == "topchef_order_details"
    assert order_template_name(config, "status_changed") == "topchef_order_status"


def test_first_contact_is_prompted_once_then_follows_saved_choice():
    config = type("Config", (), {
        "first_order_template_name": "topchef_first_order_details",
        "order_details_template_name": "topchef_order_details",
        "order_status_template_name": "topchef_order_status",
    })()
    assert order_message_plan(config, "unknown", "created", True) == (
        "topchef_first_order_details", True,
    )
    assert order_message_plan(config, "pending", "created", True) is None
    assert order_message_plan(config, "disabled", "created", True) is None
    assert order_message_plan(config, "unavailable", "created", True) is None
    assert order_message_plan(config, "enabled", "created", False) == (
        "topchef_order_details", False,
    )
    assert order_message_plan(config, "enabled", "status_changed", False) == (
        "topchef_order_status", False,
    )
