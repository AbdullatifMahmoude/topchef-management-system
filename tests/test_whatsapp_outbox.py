from datetime import timedelta

import pytest

from app.modules.settings.whatsapp_outbox import (
    WhatsAppOutboxWorker,
    enqueue_order_notification,
    order_event_key,
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


def test_outbox_worker_connection_failure_backoff_is_bounded():
    worker = WhatsAppOutboxWorker(poll_seconds=2)
    delays = [min(60, worker.poll_seconds * (2 ** min(attempt, 5))) for attempt in range(1, 8)]

    assert delays == [4, 8, 16, 32, 60, 60, 60]
