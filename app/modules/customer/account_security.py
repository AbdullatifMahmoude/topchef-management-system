import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jose import JWTError, jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.modules.customer.models import CustomerDevice

ACCESS_MINUTES = 15
DEVICE_DAYS = 90
COOKIE_NAME = "topchef_customer_refresh"


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_customer_access(customer_id: int, device_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode({
        "sub": f"customer:{customer_id}", "customer_id": customer_id,
        "device_id": device_id, "type": "customer_access",
        "iat": now, "exp": now + timedelta(minutes=ACCESS_MINUTES),
    }, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_customer_access(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], options={"require_exp": True})
    except JWTError as exc:
        raise AuthenticationError("انتهت جلسة العميل") from exc
    if payload.get("type") != "customer_access" or not isinstance(payload.get("customer_id"), int):
        raise AuthenticationError("جلسة العميل غير صالحة")
    return payload


async def create_device_session(db, customer_id: int, device_name: str) -> tuple[str, str, CustomerDevice]:
    raw_refresh = secrets.token_urlsafe(48)
    device = CustomerDevice(
        id=str(uuid4()), customer_id=customer_id, refresh_token_hash=token_hash(raw_refresh),
        device_name=(device_name.strip() or "جهاز")[:120],
        expires_at=datetime.utcnow() + timedelta(days=DEVICE_DAYS),
    )
    db.add(device)
    await db.flush()
    return create_customer_access(customer_id, device.id), raw_refresh, device


async def rotate_device_session(db, raw_refresh: str) -> tuple[str, str, CustomerDevice]:
    result = await db.execute(select(CustomerDevice).where(CustomerDevice.refresh_token_hash == token_hash(raw_refresh)))
    device = result.scalar_one_or_none()
    if not device or device.revoked_at or device.expires_at < datetime.utcnow():
        raise AuthenticationError("انتهت جلسة الجهاز")
    new_refresh = secrets.token_urlsafe(48)
    device.refresh_token_hash = token_hash(new_refresh)
    device.last_used_at = datetime.utcnow()
    device.expires_at = datetime.utcnow() + timedelta(days=DEVICE_DAYS)
    await db.flush()
    return create_customer_access(device.customer_id, device.id), new_refresh, device
