import hashlib
import json
import re
import secrets
from urllib.parse import quote

from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthenticationServiceUnavailable
from app.modules.customer.phone import normalize_egyptian_phone
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp import inbound_verification_config_ready

CHALLENGE_TTL_SECONDS = 60
_CODE_RE = re.compile(r"\bTCV-([A-Z0-9]{8})\b", re.IGNORECASE)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _id_key(challenge_id: str) -> str:
    return f"wa:verify:id:{_digest(challenge_id)}"


def _code_key(code: str) -> str:
    return f"wa:verify:code:{_digest(code.upper())}"


async def _setex(redis, key: str, ttl: int, value: str) -> None:
    result = await redis.setex(key, ttl, value)
    if result is False:
        raise AuthenticationServiceUnavailable()


async def create_inbound_challenge(db, redis, *, phone: str, actor_type: str,
                                   actor_id: int | None, purpose: str) -> dict:
    if not settings.WHATSAPP_VERIFICATION_ENABLED:
        raise AuthenticationServiceUnavailable()
    if redis is None:
        raise AuthenticationServiceUnavailable()
    config = await SettingsService(db, redis).get_whatsapp_settings()
    if not inbound_verification_config_ready(config):
        raise AuthenticationServiceUnavailable()
    normalized = normalize_egyptian_phone(phone)
    if not re.fullmatch(r"01[0125]\d{8}", normalized):
        raise AuthenticationError("رقم الهاتف غير صالح")
    rate_key = f"wa:verify:rate:{_digest(normalized)}"
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, 3600)
    if count > 10:
        raise AuthenticationError("تم تجاوز عدد محاولات التحقق. حاول لاحقًا")
    challenge_id = secrets.token_urlsafe(32)
    code = secrets.token_hex(4).upper()
    record = {
        "phone": normalized, "actor_type": actor_type, "actor_id": actor_id,
        "purpose": purpose, "verified": False,
    }
    await _setex(redis, _id_key(challenge_id), CHALLENGE_TTL_SECONDS, json.dumps(record))
    await _setex(redis, _code_key(code), CHALLENGE_TTL_SECONDS, challenge_id)
    business_phone = re.sub(r"\D", "", config.business_phone_number)
    message = quote(f"تأكيد حساب توب شيف TCV-{code}")
    return {
        "challenge_id": challenge_id,
        "whatsapp_url": f"https://wa.me/{business_phone}?text={message}",
        "expires_in": CHALLENGE_TTL_SECONDS,
    }


async def consume_incoming_message(redis, sender: str, message: str) -> bool:
    if not settings.WHATSAPP_VERIFICATION_ENABLED:
        return False
    if redis is None:
        return False
    match = _CODE_RE.search(message or "")
    if not match:
        return False
    code = match.group(1).upper()
    challenge_id = await redis.get(_code_key(code))
    if not challenge_id:
        return False
    raw = await redis.get(_id_key(challenge_id))
    if not raw:
        return False
    record = json.loads(raw)
    sender_phone = normalize_egyptian_phone(sender)
    if not secrets.compare_digest(record["phone"], sender_phone):
        return False
    record["verified"] = True
    await _setex(redis, _id_key(challenge_id), CHALLENGE_TTL_SECONDS, json.dumps(record))
    await redis.delete(_code_key(code))
    return True


async def challenge_status(redis, challenge_id: str) -> bool:
    if redis is None:
        raise AuthenticationServiceUnavailable()
    raw = await redis.get(_id_key(challenge_id))
    return bool(raw and json.loads(raw).get("verified"))


async def consume_verified_challenge(redis, challenge_id: str, *, actor_type: str,
                                     purpose: str) -> dict:
    if redis is None:
        raise AuthenticationServiceUnavailable()
    key = _id_key(challenge_id)
    raw = await redis.getdel(key)
    if not raw:
        raise AuthenticationError("انتهت صلاحية التحقق")
    record = json.loads(raw)
    valid = record.get("verified") and record.get("actor_type") == actor_type and record.get("purpose") == purpose
    if not valid:
        raise AuthenticationError("لم يتم تأكيد رقم واتساب")
    return record
