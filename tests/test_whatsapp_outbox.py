from datetime import timedelta

from app.modules.settings.whatsapp_outbox import order_event_key, retry_delay


def test_order_outbox_key_is_idempotent_for_same_event():
    order = {"id": 7, "order_number": "A-7", "order_status": "confirmed", "total_amount": "50.00"}
    assert order_event_key(order, "created") == order_event_key(dict(order), "created")


def test_order_outbox_key_changes_for_update_or_payload_change():
    order = {"id": 7, "order_status": "confirmed"}
    changed = {"id": 7, "order_status": "completed"}
    assert order_event_key(order, "created") != order_event_key(order, "updated")
    assert order_event_key(order, "updated") != order_event_key(changed, "updated")


def test_outbox_retry_uses_bounded_exponential_backoff():
    assert retry_delay(1) == timedelta(seconds=2)
    assert retry_delay(4) == timedelta(seconds=16)
    assert retry_delay(20) == timedelta(seconds=300)
