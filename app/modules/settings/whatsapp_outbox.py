import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.modules.customer.models import Customer
from app.modules.settings.models import WhatsAppOutbox
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp import (
    build_order_message,
    order_template_parameters,
    normalize_whatsapp_phone,
    send_template_message,
    get_whatsapp_http_client,
    whatsapp_config_ready,
)

ENABLE_ORDER_UPDATES = "ENABLE_ORDER_UPDATES"
DISABLE_ORDER_UPDATES = "DISABLE_ORDER_UPDATES"
PERMANENT_RECIPIENT_ERROR_CODES = {131026}


def order_event_key(order: dict, event_type: str) -> str:
    fingerprint = json.dumps(order, sort_keys=True, separators=(",", ":"), default=str)
    raw = f"order:{order.get('id')}:{event_type}:{fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** max(1, attempt)))


def order_template_name(config, event_type: str, *, first_order: bool = False) -> str:
    if first_order:
        return config.first_order_template_name
    return (
        config.order_status_template_name
        if event_type == "status_changed"
        else config.order_details_template_name
    )


def order_message_plan(config, customer_status: str, event_type: str, initial_contact_allowed: bool):
    first_order = event_type == "created" and customer_status == "unknown" and initial_contact_allowed
    if first_order:
        return config.first_order_template_name, True
    if customer_status == "enabled":
        return order_template_name(config, event_type), False
    return None


async def enqueue_order_notification(db: AsyncSession, order: dict, event_type: str) -> bool:
    phone = normalize_whatsapp_phone(order.get("customer_phone"))
    customer_id = order.get("customer_id")
    if not phone or not customer_id:
        return False
    config = await SettingsService(db).get_whatsapp_settings()
    customer = await db.scalar(
        select(Customer).where(Customer.id == customer_id).with_for_update()
    )
    if not customer:
        return False
    plan = order_message_plan(
        config, customer.whatsapp_status, event_type,
        bool(order.get("whatsapp_initial_contact_allowed")),
    )
    if not plan:
        return False
    template_name, first_order = plan
    if not whatsapp_config_ready(config, template_name=template_name):
        return False
    event_key = order_event_key(order, event_type)
    if await db.scalar(select(WhatsAppOutbox.id).where(WhatsAppOutbox.event_key == event_key)):
        return False
    button_payloads = [ENABLE_ORDER_UPDATES, DISABLE_ORDER_UPDATES] if first_order else []
    parameters = order_template_parameters(order, event_type, first_order=first_order)
    db.add(WhatsAppOutbox(
        event_key=event_key,
        order_id=order.get("id"),
        customer_id=customer.id,
        phone=phone,
        template_name=template_name,
        message_text=build_order_message(order, event_type),
        template_parameters=json.dumps(parameters, ensure_ascii=False),
        button_payloads=json.dumps(button_payloads),
    ))
    if first_order:
        customer.whatsapp_status = "pending"
        customer.whatsapp_checked_at = datetime.now(UTC).replace(tzinfo=None)
        customer.whatsapp_failure_reason = None
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
                if not processed:
                    await asyncio.sleep(self.poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("WhatsApp outbox worker failed: %s", exc, exc_info=True)
                await asyncio.sleep(self.poll_seconds)

    async def process_once(self) -> int:
        now = datetime.utcnow()
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
                parameters = json.loads(row.template_parameters) if row.template_parameters else [row.message_text]
                button_payloads = json.loads(row.button_payloads) if row.button_payloads else []
                send_result = await send_template_message(
                    row.phone, parameters, row.template_name, button_payloads=button_payloads,
                    config=config, token=token, client=client,
                )
                async with db.begin():
                    current = await db.get(WhatsAppOutbox, row.id, with_for_update=True)
                    if not current:
                        continue
                    current.attempts += 1
                    current.updated_at = datetime.utcnow()
                    if send_result.accepted:
                        current.status = "sent"
                        current.sent_at = datetime.utcnow()
                        current.meta_message_id = send_result.message_id
                        current.delivery_status = "accepted"
                        current.delivery_updated_at = datetime.utcnow()
                        current.last_error = None
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
                        current.next_attempt_at = datetime.utcnow() + retry_delay(current.attempts)
                        current.last_error = send_result.error or "Temporary WhatsApp delivery failure"
            return len(rows)


whatsapp_outbox_worker = WhatsAppOutboxWorker()
