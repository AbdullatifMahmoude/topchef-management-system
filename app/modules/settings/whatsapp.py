import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings as app_settings
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
ORDER_TYPE_NAMES = {"delivery": "توصيل", "takeaway": "استلام من المطعم", "hall": "صالة"}
PAYMENT_METHOD_NAMES = {"cash": "نقدي", "instapay": "إنستا باي", "wallet": "محفظة إلكترونية"}
_http_client: httpx.AsyncClient | None = None


@dataclass(frozen=True)
class WhatsAppSendResult:
    accepted: bool
    message_id: str | None = None
    error: str | None = None
    error_code: int | None = None


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
        not app_settings.WHATSAPP_INTEGRATION_PAUSED
        and settings.enabled
        and settings.api_key_configured
        and settings.phone_number_id.strip()
        and settings.graph_api_version.strip()
        and settings.language_code.strip()
        and template_name.strip()
    )


def inbound_verification_config_ready(settings) -> bool:
    """Fail closed unless the complete direct Meta webhook integration is configured."""
    return bool(
        not app_settings.WHATSAPP_INTEGRATION_PAUSED
        and settings.enabled
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


def _amount(value: Any) -> str:
    return f"{Decimal(str(value or 0)):.2f}"


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").lower()


def _items_text(order: dict[str, Any]) -> str:
    items = order.get("items") or []
    if not items:
        return "لا توجد أصناف"
    lines = []
    for item in items:
        name = item.get("product_name") or f"صنف {item.get('product_id', '')}"
        lines.append(f"{item.get('quantity', 1)} × {name} — {_money(item.get('total_price'))}")
    return "\n".join(lines)


def order_template_parameters(order: dict[str, Any], event_type: str, *, first_order: bool = False) -> list[str]:
    order_number = str(order.get("order_number") or "-")
    status = STATUS_NAMES.get(_value(order.get("order_status")), str(order.get("order_status") or "-"))
    if event_type == "status_changed":
        return [order_number, status, _amount(order.get("total_amount"))]

    common = [
        order_number,
        status,
        ORDER_TYPE_NAMES.get(_value(order.get("order_type")), str(order.get("order_type") or "-")),
        _items_text(order),
        _amount(order.get("subtotal")),
        _amount(order.get("discount_amount")),
        _amount(order.get("delivery_fee")),
        _amount(order.get("total_amount")),
        PAYMENT_METHOD_NAMES.get(_value(order.get("payment_method")), str(order.get("payment_method") or "-")),
        str(order.get("customer_address") or "استلام من المطعم"),
        str(order.get("customer_notes") or "لا توجد"),
    ]
    if first_order:
        return common
    update_label = "تم تعديل تفاصيل الطلب" if event_type == "updated" else "تم استلام طلب جديد"
    return [update_label, *common]


def build_order_message(order: dict[str, Any], event_type: str) -> str:
    headings = {
        "created": "تم إنشاء طلبك بنجاح",
        "updated": "تم تعديل تفاصيل طلبك",
        "status_changed": "تحديث جديد على حالة طلبك",
    }
    lines = [
        headings.get(event_type, "تحديث على طلبك"),
        f"رقم الطلب: {order.get('order_number', '-')}",
        f"الحالة: {STATUS_NAMES.get(_value(order.get('order_status')), order.get('order_status', '-'))}",
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

    template_name = (
        settings.order_status_template_name
        if event_type == "status_changed"
        else settings.order_details_template_name
    )
    if not token or not whatsapp_config_ready(settings, template_name=template_name):
        logger.debug("WhatsApp skipped for order %s: integration is incomplete or disabled", order.get("order_number"))
        return False

    result = await send_template_message(
        phone, order_template_parameters(order, event_type), template_name,
        config=settings, token=token, client=get_whatsapp_http_client(),
    )
    return result.accepted


async def send_template_message(
    phone: str, parameters: list[str], template_name: str, *, button_payloads: list[str] | None = None,
    config=None, token: str | None = None, client: httpx.AsyncClient | None = None,
) -> WhatsAppSendResult:
    normalized = normalize_whatsapp_phone(phone)
    if not normalized:
        return WhatsAppSendResult(False, error="Invalid Egyptian mobile number")
    settings = config
    if settings is None or token is None:
        async with AsyncSessionLocal() as db:
            service = SettingsService(db)
            settings = await service.get_whatsapp_settings()
            token = await service.get_whatsapp_access_token()
    if not token or not whatsapp_config_ready(settings, template_name=template_name):
        return WhatsAppSendResult(False, error="WhatsApp integration is incomplete or disabled")
    components = [{
        "type": "body",
        "parameters": [{"type": "text", "text": str(value)} for value in parameters],
    }]
    for index, payload_value in enumerate(button_payloads or []):
        components.append({
            "type": "button", "sub_type": "quick_reply", "index": str(index),
            "parameters": [{"type": "payload", "payload": payload_value}],
        })
    payload = {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": normalized,
        "type": "template", "template": {
            "name": template_name, "language": {"code": settings.language_code}, "components": components,
        },
    }
    try:
        response = await (client or get_whatsapp_http_client()).post(
            f"https://graph.facebook.com/{settings.graph_api_version}/{settings.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload,
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.is_success:
            messages = data.get("messages") or []
            message_id = messages[0].get("id") if messages else None
            return WhatsAppSendResult(True, message_id=message_id)
        error = data.get("error") or {}
        error_code = error.get("code")
        logger.warning("WhatsApp template '%s' rejected status=%s", template_name, response.status_code)
        return WhatsAppSendResult(
            False, error=error.get("message") or f"Meta API rejected the message ({response.status_code})",
            error_code=int(error_code) if str(error_code).isdigit() else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("WhatsApp template '%s' request failed: %s", template_name, type(exc).__name__)
        return WhatsAppSendResult(False, error="WhatsApp request failed")


async def send_template_text(
    phone: str, text: str, template_name: str, *, config=None,
    token: str | None = None, client: httpx.AsyncClient | None = None,
) -> WhatsAppSendResult:
    return await send_template_message(
        phone, [text], template_name, config=config, token=token, client=client,
    )


async def send_session_message(
    phone: str,
    text: str,
    *,
    interactive: dict[str, Any] | None = None,
    config=None,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> WhatsAppSendResult:
    """Send only a non-template message inside a customer-opened service window."""
    normalized = normalize_whatsapp_phone(phone)
    if not normalized:
        return WhatsAppSendResult(False, error="Invalid Egyptian mobile number")
    settings = config
    if settings is None or token is None:
        async with AsyncSessionLocal() as db:
            service = SettingsService(db)
            settings = await service.get_whatsapp_settings()
            token = await service.get_whatsapp_access_token()
    if not token or not inbound_verification_config_ready(settings):
        return WhatsAppSendResult(False, error="WhatsApp integration is incomplete or disabled")
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized,
    }
    if interactive:
        payload.update({"type": "interactive", "interactive": interactive})
    else:
        payload.update({"type": "text", "text": {"preview_url": True, "body": text}})
    try:
        response = await (client or get_whatsapp_http_client()).post(
            f"https://graph.facebook.com/{settings.graph_api_version}/{settings.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.is_success:
            messages = data.get("messages") or []
            return WhatsAppSendResult(True, message_id=messages[0].get("id") if messages else None)
        error = data.get("error") or {}
        code = error.get("code")
        return WhatsAppSendResult(
            False,
            error=error.get("message") or f"Meta API rejected the message ({response.status_code})",
            error_code=int(code) if str(code).isdigit() else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("WhatsApp session message failed: %s", type(exc).__name__)
        return WhatsAppSendResult(False, error="WhatsApp request failed")
