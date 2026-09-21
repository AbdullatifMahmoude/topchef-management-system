import hashlib
import hmac
import json
import re
import secrets

from app.core.config import settings
from app.core.email import EmailSender
from app.core.exceptions import (
    AuthenticationError,
    AuthenticationServiceUnavailable,
)
from app.core.logging import logger

CHALLENGE_TTL_SECONDS = 600
MAX_VERIFY_ATTEMPTS = 5
MAX_REQUESTS_PER_HOUR = 5
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: str | None) -> str:
    email = (value or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise AuthenticationError("البريد الإلكتروني غير صالح")
    return email


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _challenge_key(challenge_id: str) -> str:
    return f"email:verify:{_digest(challenge_id)}"


async def create_email_challenge(
    redis,
    *,
    email: str,
    actor_type: str,
    actor_id: int | None,
    purpose: str,
    phone: str | None = None,
    send_email: bool = True,
) -> dict:
    if redis is None or not settings.EMAIL_ENABLED:
        raise AuthenticationServiceUnavailable()
    normalized = normalize_email(email)
    rate_key = f"email:verify:rate:{_digest(normalized)}"
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, 3600)
    if count > MAX_REQUESTS_PER_HOUR:
        raise AuthenticationError("تم تجاوز عدد محاولات التحقق. حاول لاحقًا")

    challenge_id = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    record = {
        "email": normalized,
        "phone": phone,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "purpose": purpose,
        "code_digest": _digest(code),
        "attempts": 0,
        "verified": False,
    }
    saved = await redis.setex(
        _challenge_key(challenge_id),
        CHALLENGE_TTL_SECONDS,
        json.dumps(record),
    )
    if saved is False:
        raise AuthenticationServiceUnavailable()

    if send_email:
        try:
            await EmailSender().send(
                to_address=normalized,
                subject="رمز التحقق من Top Chef",
                text_body=(
                    f"رمز التحقق الخاص بك هو: {code}\n"
                    "ينتهي الرمز خلال 10 دقائق. لا تشاركه مع أي شخص."
                ),
            )
        except Exception as exc:
            await redis.delete(_challenge_key(challenge_id))
            logger.error("Email verification delivery failed: %s", type(exc).__name__)
            raise AuthenticationServiceUnavailable() from exc

    return {"challenge_id": challenge_id, "expires_in": CHALLENGE_TTL_SECONDS}


async def verify_email_challenge(redis, challenge_id: str, code: str) -> bool:
    if redis is None:
        raise AuthenticationServiceUnavailable()
    key = _challenge_key(challenge_id)
    raw = await redis.get(key)
    if not raw:
        raise AuthenticationError("انتهت صلاحية رمز التحقق")
    record = json.loads(raw)
    attempts = int(record.get("attempts", 0)) + 1
    if attempts > MAX_VERIFY_ATTEMPTS:
        await redis.delete(key)
        raise AuthenticationError("تم تجاوز عدد محاولات إدخال الرمز")
    if not hmac.compare_digest(record.get("code_digest", ""), _digest(code.strip())):
        record["attempts"] = attempts
        await redis.setex(key, CHALLENGE_TTL_SECONDS, json.dumps(record))
        raise AuthenticationError("رمز التحقق غير صحيح")
    record["attempts"] = attempts
    record["verified"] = True
    await redis.setex(key, CHALLENGE_TTL_SECONDS, json.dumps(record))
    return True


async def consume_email_challenge(
    redis,
    challenge_id: str,
    *,
    actor_type: str,
    purpose: str,
) -> dict:
    if redis is None:
        raise AuthenticationServiceUnavailable()
    raw = await redis.getdel(_challenge_key(challenge_id))
    if not raw:
        raise AuthenticationError("انتهت صلاحية التحقق")
    record = json.loads(raw)
    valid = (
        record.get("verified") is True
        and record.get("actor_type") == actor_type
        and record.get("purpose") == purpose
    )
    if not valid:
        raise AuthenticationError("لم يتم تأكيد البريد الإلكتروني")
    return record
