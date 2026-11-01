import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.enums import OrderStatus
from app.core.logging import logger
from app.modules.customer.models import Customer
from app.modules.orders.models import Order
from app.modules.settings.models import WhatsAppOrderSubscription, WhatsAppOutbox
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp import (
    build_order_message,
    get_whatsapp_http_client,
    normalize_whatsapp_phone,
    send_session_message,
    send_template_message,
)

PERMANENT_RECIPIENT_ERROR_CODES = {131026}


def order_event_key(order: dict, event_type: str) -> str:
    fingerprint = json.dumps(order, sort_keys=True, separators=(",", ":"), default=str)
    raw = f"order:{order.get('id')}:{event_type}:{fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** max(1, attempt)))


async def enqueue_order_notification(db: AsyncSession, order: dict, event_type: str) -> bool:
    phone = normalize_whatsapp_phone(order.get("customer_phone"))
    customer_id = order.get("customer_id")
    if not phone or not customer_id:
        return False
    now = datetime.now(UTC).replace(tzinfo=None)
    subscription = await db.scalar(
        select(WhatsAppOrderSubscription).where(
            WhatsAppOrderSubscription.order_id == order.get("id"),
            WhatsAppOrderSubscription.whatsapp_phone == phone,
            WhatsAppOrderSubscription.status == "active",
            WhatsAppOrderSubscription.service_window_expires_at > now,
        ).with_for_update()
    )
    if not subscription:
        return False
    event_key = order_event_key(order, event_type)
    if await db.scalar(select(WhatsAppOutbox.id).where(WhatsAppOutbox.event_key == event_key)):
        return False
    db.add(WhatsAppOutbox(
        event_key=event_key,
        order_id=order.get("id"),
        customer_id=customer_id,
        phone=phone,
        template_name="__session__",
        message_text=build_order_message(order, event_type),
        message_type="session_text",
        service_window_expires_at=subscription.service_window_expires_at,
        subscription_id=subscription.id,
    ))
    return True


async def enqueue_bulk_notifications(
    db: AsyncSession, phones: list[str], message: str, template_name: str
) -> int:
    batch_id = uuid4().hex
    queued = 0
    for index, raw_phone in enumerate(phones):
        phone = normalize_whatsapp_phone(raw_phone)
        if not phone:
            continue
        event_key = hashlib.sha256(f"bulk:{batch_id}:{index}:{phone}".encode()).hexdigest()
        db.add(WhatsAppOutbox(
            event_key=event_key, phone=phone, template_name=template_name,
            message_text=message,
            template_parameters=json.dumps([message], ensure_ascii=False),
        ))
        queued += 1
    return queued


class WhatsAppOutboxWorker:
    def __init__(self, poll_seconds: float = 2.0, batch_size: int = 25, max_attempts: int = 5):
        self.poll_seconds = poll_seconds
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self._task: asyncio.Task | None = None
        self._failure_count = 0

    async def start(self):
        if not self._task:
            self._task = asyncio.create_task(self._run(), name="whatsapp-outbox-worker")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self):
        while True:
            try:
                processed = await self.process_once()
                self._failure_count = 0
                if not processed:
                    await asyncio.sleep(self.poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("WhatsApp outbox worker failed: %s", exc, exc_info=True)
                self._failure_count += 1
                await asyncio.sleep(min(60, self.poll_seconds * (2 ** min(self._failure_count, 5))))

    async def process_once(self) -> int:
        if settings.WHATSAPP_INTEGRATION_PAUSED:
            return 0
        now = datetime.now(UTC).replace(tzinfo=None)
        stale = now - timedelta(minutes=5)
        async with AsyncSessionLocal() as db:
            async with db.begin():
                settings_service = SettingsService(db)
                config = await settings_service.get_whatsapp_settings()
                token = await settings_service.get_whatsapp_access_token()
                result = await db.execute(
                    select(WhatsAppOutbox)
                    .where(
                        or_(
                            (WhatsAppOutbox.status == "pending") & (WhatsAppOutbox.next_attempt_at <= now),
                            (WhatsAppOutbox.status == "processing") & (WhatsAppOutbox.updated_at <= stale),
                        )
                    )
                    .order_by(WhatsAppOutbox.id)
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
                rows = list(result.scalars().all())
                for row in rows:
                    row.status = "processing"
                    row.updated_at = now

            client = get_whatsapp_http_client()
            for row in rows:
                check_now = datetime.now(UTC).replace(tzinfo=None)
                if row.message_type in {"session_text", "interactive"}:
                    window_open = bool(row.service_window_expires_at and row.service_window_expires_at > check_now)
                    if row.subscription_id:
                        async with db.begin():
                            subscription = await db.get(WhatsAppOrderSubscription, row.subscription_id)
                            window_open = bool(
                                subscription
                                and subscription.status == "active"
                                and subscription.whatsapp_phone == row.phone
                                and subscription.service_window_expires_at > check_now
                            )
                    if not window_open:
                        async with db.begin():
                            current = await db.get(WhatsAppOutbox, row.id, with_for_update=True)
                            if current:
                                current.status = "skipped"
                                current.skip_reason = "customer_service_window_closed"
                                current.updated_at = check_now
                        continue
                parameters = json.loads(row.template_parameters) if row.template_parameters else [row.message_text]
                button_payloads = json.loads(row.button_payloads) if row.button_payloads else []
                if row.message_type in {"session_text", "interactive"}:
                    interactive = json.loads(row.interactive_payload) if row.interactive_payload else None
                    send_result = await send_session_message(
                        row.phone, row.message_text, interactive=interactive,
                        config=config, token=token, client=client,
                    )
                else:
                    send_result = await send_template_message(
                        row.phone, parameters, row.template_name, button_payloads=button_payloads,
                        config=config, token=token, client=client,
                    )
                async with db.begin():
                    current = await db.get(WhatsAppOutbox, row.id, with_for_update=True)
                    if not current:
                        continue
                    current.attempts += 1
                    current.updated_at = datetime.now(UTC).replace(tzinfo=None)
                    if send_result.accepted:
                        current.status = "sent"
                        current.sent_at = datetime.now(UTC).replace(tzinfo=None)
                        current.meta_message_id = send_result.message_id
                        current.delivery_status = "accepted"
                        current.delivery_updated_at = datetime.now(UTC).replace(tzinfo=None)
                        current.last_error = None
                        if current.subscription_id and current.order_id:
                            subscription = await db.get(
                                WhatsAppOrderSubscription, current.subscription_id, with_for_update=True
                            )
                            order = await db.get(Order, current.order_id)
                            if subscription and order and order.order_status in {
                                OrderStatus.COMPLETED, OrderStatus.DELIVERED, OrderStatus.CANCELLED,
                            }:
                                subscription.status = "stopped"
                                subscription.stopped_at = datetime.now(UTC).replace(tzinfo=None)
                    elif (
                        send_result.error_code in PERMANENT_RECIPIENT_ERROR_CODES
                        or current.attempts >= self.max_attempts
                    ):
                        current.status = "failed"
                        current.last_error = send_result.error or "Meta API rejected or did not accept the message"
                        if current.customer_id:
                            customer = await db.get(Customer, current.customer_id, with_for_update=True)
                            if customer and send_result.error_code in PERMANENT_RECIPIENT_ERROR_CODES:
                                customer.whatsapp_status = "unavailable"
                                customer.whatsapp_checked_at = datetime.now(UTC).replace(tzinfo=None)
                                customer.whatsapp_failure_reason = current.last_error[:255]
                            elif (
                                customer
                                and current.template_name == config.first_order_template_name
                                and customer.whatsapp_status == "pending"
                            ):
                                customer.whatsapp_status = "unknown"
                                customer.whatsapp_checked_at = datetime.now(UTC).replace(tzinfo=None)
                                customer.whatsapp_failure_reason = current.last_error[:255]
                    else:
                        current.status = "pending"
                        current.next_attempt_at = datetime.now(UTC).replace(tzinfo=None) + retry_delay(current.attempts)
                        current.last_error = send_result.error or "Temporary WhatsApp delivery failure"
            return len(rows)


whatsapp_outbox_worker = WhatsAppOutboxWorker()
