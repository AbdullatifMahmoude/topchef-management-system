import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.modules.settings.models import WhatsAppOutbox
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp import (
    build_order_message,
    normalize_whatsapp_phone,
    send_template_text,
    get_whatsapp_http_client,
    whatsapp_config_ready,
)


def order_event_key(order: dict, event_type: str) -> str:
    fingerprint = json.dumps(order, sort_keys=True, separators=(",", ":"), default=str)
    raw = f"order:{order.get('id')}:{event_type}:{fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** max(1, attempt)))


async def enqueue_order_notification(db: AsyncSession, order: dict, event_type: str) -> bool:
    phone = normalize_whatsapp_phone(order.get("customer_phone"))
    if not phone:
        return False
    config = await SettingsService(db).get_whatsapp_settings()
    if not whatsapp_config_ready(config, template_name=config.template_name):
        return False
    event_key = order_event_key(order, event_type)
    if await db.scalar(select(WhatsAppOutbox.id).where(WhatsAppOutbox.event_key == event_key)):
        return False
    db.add(WhatsAppOutbox(
        event_key=event_key,
        order_id=order.get("id"),
        phone=phone,
        template_name=config.template_name,
        message_text=build_order_message(order, event_type),
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
                success = await send_template_text(
                    row.phone, row.message_text, row.template_name,
                    config=config, token=token, client=client,
                )
                async with db.begin():
                    current = await db.get(WhatsAppOutbox, row.id, with_for_update=True)
                    if not current:
                        continue
                    current.attempts += 1
                    current.updated_at = datetime.utcnow()
                    if success:
                        current.status = "sent"
                        current.sent_at = datetime.utcnow()
                        current.last_error = None
                    elif current.attempts >= self.max_attempts:
                        current.status = "failed"
                        current.last_error = "Meta API rejected or did not accept the message"
                    else:
                        current.status = "pending"
                        current.next_attempt_at = datetime.utcnow() + retry_delay(current.attempts)
                        current.last_error = "Temporary WhatsApp delivery failure"
            return len(rows)


whatsapp_outbox_worker = WhatsAppOutboxWorker()
