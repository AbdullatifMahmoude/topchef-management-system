import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp_verification import consume_incoming_message

router = APIRouter(prefix="/whatsapp/webhook", tags=["WhatsApp Webhook"])


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
            for message in change.get("value", {}).get("messages", []):
                text = (message.get("text") or {}).get("body", "")
                await consume_incoming_message(redis, message.get("from", ""), text)
    return {"received": True}
