import re
from decimal import Decimal
from typing import Any

import httpx

from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.modules.settings.service import SettingsService


STATUS_NAMES = {
    "new": "تم استلام الطلب",
    "confirmed": "تم تأكيد الطلب",
    "out_for_delivery": "الطلب خرج للتوصيل",
    "delivered": "تم توصيل الطلب",
    "completed": "تم اكتمال الطلب",
    "cancelled": "تم إلغاء الطلب",
}
_http_client: httpx.AsyncClient | None = None


def get_whatsapp_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


async def close_whatsapp_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def whatsapp_config_ready(settings, *, template_name: str = "") -> bool:
    """One gate used by every WhatsApp-dependent feature."""
    return bool(
        settings.enabled
        and settings.api_key_configured
        and settings.phone_number_id.strip()
        and settings.graph_api_version.strip()
        and settings.language_code.strip()
        and template_name.strip()
    )


def inbound_verification_config_ready(settings) -> bool:
    """Fail closed unless the complete direct Meta webhook integration is configured."""
    return bool(
        settings.enabled
        and settings.api_key_configured
        and settings.phone_number_id.strip()
        and settings.business_phone_number.strip()
        and settings.webhook_verify_token_configured
        and settings.app_secret_configured
    )


def normalize_whatsapp_phone(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0020"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = "20" + digits[1:]
    elif len(digits) == 10 and digits.startswith("1"):
        digits = "20" + digits
    if not re.fullmatch(r"20(?:10|11|12|15)\d{8}", digits):
        return None
    return digits


def _money(value: Any) -> str:
    return f"{Decimal(str(value or 0)):.2f} ج.م"


def build_order_message(order: dict[str, Any], event_type: str) -> str:
    headings = {
        "created": "تم إنشاء طلبك بنجاح",
        "updated": "تم تعديل تفاصيل طلبك",
        "status_changed": "تحديث جديد على حالة طلبك",
    }
    lines = [
        headings.get(event_type, "تحديث على طلبك"),
        f"رقم الطلب: #{order.get('order_number', '-')}",
        f"الحالة: {STATUS_NAMES.get(str(order.get('order_status', '')).lower(), order.get('order_status', '-'))}",
    ]
    if event_type != "status_changed":
        items = order.get("items") or []
        if items:
            lines.append("تفاصيل الطلب:")
            for item in items:
                name = item.get("product_name") or f"صنف {item.get('product_id', '')}"
                lines.append(f"- {name} × {item.get('quantity', 1)} — {_money(item.get('total_price'))}")
        discount = Decimal(str(order.get("discount_amount") or 0))
        if discount > 0:
            lines.append(f"الخصم: {_money(discount)}")
        delivery = Decimal(str(order.get("delivery_fee") or 0))
        if delivery > 0:
            lines.append(f"التوصيل: {_money(delivery)}")
    lines.append(f"الإجمالي: {_money(order.get('total_amount'))}")
    lines.append("شكرًا لاختيارك توب شيف")
    return "\n".join(lines)


async def send_order_notification(order: dict[str, Any], event_type: str) -> bool:
    phone = normalize_whatsapp_phone(order.get("customer_phone"))
    if not phone:
        logger.debug("WhatsApp skipped for order %s: no valid Egyptian mobile", order.get("order_number"))
        return False

    async with AsyncSessionLocal() as db:
        service = SettingsService(db)
        settings = await service.get_whatsapp_settings()
        token = await service.get_whatsapp_access_token()

    if not token or not whatsapp_config_ready(settings, template_name=settings.template_name):
        logger.debug("WhatsApp skipped for order %s: integration is incomplete or disabled", order.get("order_number"))
        return False

    url = f"https://graph.facebook.com/{settings.graph_api_version}/{settings.phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "template",
        "template": {
            "name": settings.template_name,
            "language": {"code": settings.language_code},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": build_order_message(order, event_type)}],
            }],
        },
    }
    try:
        response = await get_whatsapp_http_client().post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        if response.is_success:
            logger.info("WhatsApp %s sent for order %s", event_type, order.get("order_number"))
            return True
        logger.warning(
            "WhatsApp delivery rejected for order %s status=%s",
            order.get("order_number"), response.status_code,
        )
    except Exception as exc:
        logger.warning("WhatsApp request failed for order %s: %s", order.get("order_number"), exc)
    return False


async def send_template_text(
    phone: str, text: str, template_name: str, *, config=None,
    token: str | None = None, client: httpx.AsyncClient | None = None,
) -> bool:
    normalized = normalize_whatsapp_phone(phone)
    if not normalized:
        return False
    settings = config
    if settings is None or token is None:
        async with AsyncSessionLocal() as db:
            service = SettingsService(db)
            settings = await service.get_whatsapp_settings()
            token = await service.get_whatsapp_access_token()
    if not token or not whatsapp_config_ready(settings, template_name=template_name):
        return False
    payload = {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": normalized, "type": "template",
        "template": {
            "name": template_name, "language": {"code": settings.language_code},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": text}]}],
        },
    }
    try:
        response = await (client or get_whatsapp_http_client()).post(
            f"https://graph.facebook.com/{settings.graph_api_version}/{settings.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload,
        )
        if response.is_success:
            return True
        logger.warning("WhatsApp template '%s' rejected status=%s", template_name, response.status_code)
    except Exception as exc:
        logger.warning("WhatsApp template '%s' request failed: %s", template_name, type(exc).__name__)
    return False
