import asyncio
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
_notification_tasks: set[asyncio.Task] = set()


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
        logger.info("WhatsApp skipped for order %s: no valid Egyptian mobile", order.get("order_number"))
        return False

    async with AsyncSessionLocal() as db:
        settings = await SettingsService(db).get_whatsapp_settings()
        key_row = await SettingsService(db).repo.get_setting(SettingsService.WHATSAPP_API_KEY)
        token = key_row.value_text if key_row and key_row.value_text else ""

    if not token or not whatsapp_config_ready(settings, template_name=settings.template_name):
        logger.info("WhatsApp skipped for order %s: integration is incomplete or disabled", order.get("order_number"))
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
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.is_success:
            logger.info("WhatsApp %s sent for order %s", event_type, order.get("order_number"))
            return True
        logger.warning(
            "WhatsApp delivery rejected for order %s (status=%s): %s",
            order.get("order_number"), response.status_code, response.text[:1000],
        )
    except Exception as exc:
        logger.warning("WhatsApp request failed for order %s: %s", order.get("order_number"), exc)
    return False


async def send_template_text(phone: str, text: str, template_name: str) -> bool:
    normalized = normalize_whatsapp_phone(phone)
    if not normalized:
        return False
    async with AsyncSessionLocal() as db:
        service = SettingsService(db)
        settings = await service.get_whatsapp_settings()
        key_row = await service.repo.get_setting(SettingsService.WHATSAPP_API_KEY)
        token = key_row.value_text if key_row and key_row.value_text else ""
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
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"https://graph.facebook.com/{settings.graph_api_version}/{settings.phone_number_id}/messages",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload,
            )
        if response.is_success:
            return True
        logger.warning("WhatsApp template '%s' rejected for %s: %s", template_name, normalized, response.text[:1000])
    except Exception as exc:
        logger.warning("WhatsApp template '%s' failed for %s: %s", template_name, normalized, exc)
    return False


def queue_bulk_message(phones: list[str], text: str, template_name: str) -> None:
    async def runner():
        semaphore = asyncio.Semaphore(5)
        async def send(phone: str):
            async with semaphore:
                return await send_template_text(phone, text, template_name)
        results = await asyncio.gather(*(send(phone) for phone in phones), return_exceptions=True)
        sent = sum(result is True for result in results)
        logger.info("WhatsApp bulk send finished: %s/%s accepted by Meta", sent, len(phones))
    task = asyncio.create_task(runner(), name="whatsapp-bulk-send")
    _notification_tasks.add(task)
    task.add_done_callback(_notification_tasks.discard)


def queue_order_notification(order: dict[str, Any], event_type: str) -> None:
    async def runner():
        # Let the request transaction commit before reading integration settings.
        await asyncio.sleep(0.25)
        await send_order_notification(order, event_type)

    task = asyncio.create_task(runner(), name=f"whatsapp-order-{order.get('id', 'unknown')}")
    _notification_tasks.add(task)
    task.add_done_callback(_notification_tasks.discard)
