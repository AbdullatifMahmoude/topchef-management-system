import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.customer.models import Customer
from app.modules.customer.repository import CustomerRepository
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp_verification import consume_incoming_message
from app.modules.settings.models import WhatsAppOutbox
from app.modules.settings.whatsapp_outbox import (
    DISABLE_ORDER_UPDATES,
    ENABLE_ORDER_UPDATES,
    PERMANENT_RECIPIENT_ERROR_CODES,
)

router = APIRouter(prefix="/whatsapp/webhook", tags=["WhatsApp Webhook"])

_DELIVERY_RANK = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 3}


async def record_delivery_status(db: AsyncSession, delivery: dict, redis=None) -> bool:
    message_id = delivery.get("id")
    incoming_status = delivery.get("status")
    if not message_id or incoming_status not in _DELIVERY_RANK:
        return False
    row = await db.scalar(
        select(WhatsAppOutbox).where(WhatsAppOutbox.meta_message_id == message_id)
    )
    if not row:
        return False
    current_rank = _DELIVERY_RANK.get(row.delivery_status or "accepted", 0)
    if _DELIVERY_RANK[incoming_status] < current_rank:
        return False
    row.delivery_status = incoming_status
    timestamp = delivery.get("timestamp")
    row.delivery_updated_at = (
        datetime.fromtimestamp(int(timestamp), UTC).replace(tzinfo=None)
        if timestamp else datetime.now(UTC).replace(tzinfo=None)
    )
    errors = delivery.get("errors") or []
    if errors:
        first_error = errors[0]
        row.delivery_error = first_error.get("title") or first_error.get("message") or "WhatsApp delivery failed"
        error_code = first_error.get("code")
        if row.customer_id and error_code in PERMANENT_RECIPIENT_ERROR_CODES:
            customer = await db.get(Customer, row.customer_id, with_for_update=True)
            if customer:
                customer.whatsapp_status = "unavailable"
                customer.whatsapp_checked_at = row.delivery_updated_at
                customer.whatsapp_failure_reason = row.delivery_error[:255]
                if redis:
                    await redis.delete(f"customer_profile:{customer.id}")
    else:
        row.delivery_error = None
    return True


async def record_consent_reply(db: AsyncSession, message: dict, redis=None) -> bool:
    if message.get("type") != "button":
        return False
    payload = (message.get("button") or {}).get("payload")
    if payload not in {ENABLE_ORDER_UPDATES, DISABLE_ORDER_UPDATES}:
        return False
    customer = await CustomerRepository(db).get_by_phone(message.get("from", ""))
    if not customer:
        return False
    customer.whatsapp_status = "enabled" if payload == ENABLE_ORDER_UPDATES else "disabled"
    customer.whatsapp_consent_at = datetime.now(UTC).replace(tzinfo=None)
    customer.whatsapp_checked_at = customer.whatsapp_consent_at
    customer.whatsapp_failure_reason = None
    if redis:
        await redis.delete(f"customer_profile:{customer.id}")
    return True


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
    db: AsyncSession = Depends(get_db),
):
    expected = await SettingsService(db).get_whatsapp_webhook_verify_token()
    if not expected or hub_mode != "subscribe" or not hmac.compare_digest(expected, hub_verify_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid verification token")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    secret = await SettingsService(db).get_whatsapp_app_secret()
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature")
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                await record_consent_reply(db, message, redis)
                text = (message.get("text") or {}).get("body", "")
                await consume_incoming_message(redis, message.get("from", ""), text)
            for delivery in value.get("statuses", []):
                await record_delivery_status(db, delivery, redis)
    return {"received": True}
