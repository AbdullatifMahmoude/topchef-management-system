import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import OrderStatus
from app.modules.orders.models import Order, OrderItem
from app.modules.settings.models import (
    WhatsAppConversation,
    WhatsAppInboundMessage,
    WhatsAppOrderSubscription,
    WhatsAppOutbox,
)
from app.modules.settings.whatsapp import build_order_message, normalize_whatsapp_phone


TRACK_ORDER = "TRACK_ORDER"
ENABLE_UPDATES = "ENABLE_ORDER_UPDATES"
START_ORDER = "START_ORDER"
CUSTOMER_SERVICE = "CUSTOMER_SERVICE"
ACTIVE_STATUSES = {OrderStatus.NEW, OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY}
TERMINAL_STATUSES = {OrderStatus.COMPLETED, OrderStatus.DELIVERED, OrderStatus.CANCELLED}
STATE_TTL = timedelta(minutes=10)
WINDOW = timedelta(hours=24)


def _naive_utc(timestamp: str | None = None) -> datetime:
    if timestamp and str(timestamp).isdigit():
        return datetime.fromtimestamp(int(timestamp), UTC).replace(tzinfo=None)
    return datetime.now(UTC).replace(tzinfo=None)


def _message_content(message: dict) -> tuple[str, str]:
    message_type = str(message.get("type") or "unknown")
    if message_type == "text":
        return (message.get("text") or {}).get("body", "").strip(), ""
    if message_type == "button":
        button = message.get("button") or {}
        return str(button.get("text") or "").strip(), str(button.get("payload") or "").strip()
    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        selection = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return str(selection.get("title") or "").strip(), str(selection.get("id") or "").strip()
    return "", ""


def _normalize_intent_text(value: str) -> str:
    table = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
    return " ".join(value.translate(table).lower().split())


def _order_payload(order: Order) -> dict:
    return {
        "id": order.id,
        "customer_id": order.customer_id,
        "customer_phone": order.customer_phone,
        "order_number": order.order_number,
        "order_status": order.order_status,
        "order_type": order.order_type,
        "payment_method": order.payment_method,
        "subtotal": order.subtotal,
        "discount_amount": order.discount_amount,
        "delivery_fee": order.delivery_fee,
        "total_amount": order.total_amount,
        "customer_address": order.customer_address,
        "customer_notes": order.customer_notes,
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": item.quantity,
                "total_price": item.total_price,
            }
            for item in order.items
        ],
    }


async def _orders_for_phone(db: AsyncSession, phone: str) -> list[Order]:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.address))
        .where(Order.order_status.in_(ACTIVE_STATUSES), Order.is_deleted.is_(False))
        .order_by(Order.created_at.desc())
        .limit(50)
    )
    return [order for order in result.scalars().unique() if normalize_whatsapp_phone(order.customer_phone) == phone]


async def _order_by_number(db: AsyncSession, phone: str, number: str) -> Order | None:
    clean = number.strip().lstrip("#")
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.address))
        .where(Order.order_number == clean, Order.is_deleted.is_(False))
        .order_by(Order.created_at.desc())
        .limit(10)
    )
    for order in result.scalars().unique():
        if normalize_whatsapp_phone(order.customer_phone) == phone:
            return order
    return None


def _queue_text(
    db: AsyncSession,
    phone: str,
    text: str,
    window_expires_at: datetime,
    *,
    order_id: int | None = None,
    customer_id: int | None = None,
    subscription_id: int | None = None,
    interactive: dict | None = None,
) -> None:
    db.add(WhatsAppOutbox(
        event_key=uuid4().hex,
        order_id=order_id,
        customer_id=customer_id,
        phone=phone,
        template_name="__session__",
        message_text=text,
        message_type="interactive" if interactive else "session_text",
        interactive_payload=json.dumps(interactive, ensure_ascii=False) if interactive else None,
        service_window_expires_at=window_expires_at,
        subscription_id=subscription_id,
    ))


async def _set_state(db: AsyncSession, phone: str, state: str, now: datetime) -> None:
    conversation = await db.get(WhatsAppConversation, phone, with_for_update=True)
    if not conversation:
        conversation = WhatsAppConversation(whatsapp_phone=phone)
        db.add(conversation)
    conversation.state = state
    conversation.expires_at = now + STATE_TTL if state != "idle" else None


async def _activate(db: AsyncSession, order: Order, phone: str, now: datetime) -> None:
    if normalize_whatsapp_phone(order.customer_phone) != phone:
        raise ValueError("phone_mismatch")
    subscription = await db.scalar(
        select(WhatsAppOrderSubscription)
        .where(WhatsAppOrderSubscription.order_id == order.id)
        .with_for_update()
    )
    if not subscription:
        subscription = WhatsAppOrderSubscription(
            order_id=order.id,
            customer_id=order.customer_id,
            whatsapp_phone=phone,
            activated_at=now,
            last_customer_message_at=now,
            service_window_expires_at=now + WINDOW,
        )
        db.add(subscription)
        await db.flush()
    else:
        subscription.whatsapp_phone = phone
        subscription.status = "active"
        subscription.last_customer_message_at = now
        subscription.service_window_expires_at = now + WINDOW
        subscription.stopped_at = None
    _queue_text(
        db, phone, build_order_message(_order_payload(order), "created"), now + WINDOW,
        order_id=order.id, customer_id=order.customer_id, subscription_id=subscription.id,
    )
    await _set_state(db, phone, "idle", now)


async def _renew_windows(db: AsyncSession, phone: str, now: datetime) -> None:
    rows = list((await db.execute(
        select(WhatsAppOrderSubscription)
        .where(
            WhatsAppOrderSubscription.whatsapp_phone == phone,
            WhatsAppOrderSubscription.status == "active",
        )
        .with_for_update()
    )).scalars())
    for subscription in rows:
        subscription.last_customer_message_at = now
        subscription.service_window_expires_at = now + WINDOW


async def process_incoming_message(
    db: AsyncSession, message: dict, config, *, suppress_routing: bool = False
) -> str:
    message_id = str(message.get("id") or "").strip()
    phone = normalize_whatsapp_phone(message.get("from"))
    if not message_id or not phone:
        return "invalid_message"
    if await db.scalar(select(WhatsAppInboundMessage.id).where(WhatsAppInboundMessage.meta_message_id == message_id)):
        return "duplicate"

    text, payload = _message_content(message)
    now = _naive_utc(message.get("timestamp"))
    inbound = WhatsAppInboundMessage(
        meta_message_id=message_id,
        whatsapp_phone=phone,
        message_type=str(message.get("type") or "unknown"),
        text=text or None,
        button_payload=payload or None,
        received_at=now,
    )
    db.add(inbound)
    await _renew_windows(db, phone, now)
    if suppress_routing:
        inbound.processed_at = datetime.now(UTC).replace(tzinfo=None)
        inbound.processing_result = "verification_consumed"
        return "verification_consumed"

    conversation = await db.get(WhatsAppConversation, phone)
    state = "idle"
    if conversation and conversation.expires_at and conversation.expires_at > now:
        state = conversation.state
    elif conversation:
        await _set_state(db, phone, "idle", now)

    normalized_text = _normalize_intent_text(text)
    intent = payload or normalized_text
    result = "fallback"
    window_end = now + WINDOW

    if intent.startswith("ENABLE_ORDER:"):
        order_id = int(intent.split(":", 1)[1])
        order = await db.get(Order, order_id)
        if order and order.order_status in ACTIVE_STATUSES and normalize_whatsapp_phone(order.customer_phone) == phone:
            order = await _order_by_number(db, phone, order.order_number)
            await _activate(db, order, phone, now)
            result = "updates_enabled"
        else:
            _queue_text(db, phone, "تعذر تفعيل الطلب. تأكد أنك تستخدم نفس الرقم المسجل في الطلب.", window_end)
            result = "ownership_rejected"
    elif intent == ENABLE_UPDATES or ("تحديث" in normalized_text and ("استلم" in normalized_text or "استقبال" in normalized_text)):
        orders = await _orders_for_phone(db, phone)
        if len(orders) == 1:
            await _activate(db, orders[0], phone, now)
            result = "updates_enabled"
        elif len(orders) > 1:
            rows = [{
                "id": f"ENABLE_ORDER:{order.id}",
                "title": f"طلب #{order.order_number}"[:24],
                "description": str(getattr(order.order_status, "value", order.order_status))[:72],
            } for order in orders[:10]]
            interactive = {
                "type": "list",
                "body": {"text": "اختر الطلب الذي تريد استقبال تحديثاته"},
                "action": {"button": "اختيار الطلب", "sections": [{"title": "طلباتك النشطة", "rows": rows}]},
            }
            _queue_text(db, phone, "اختر الطلب", window_end, interactive=interactive)
            result = "updates_choice_sent"
        else:
            _queue_text(db, phone, "لم نجد طلبًا نشطًا بنفس رقم واتساب الحالي. تأكد أنك تراسلنا من الرقم المسجل في الطلب.", window_end)
            result = "no_matching_order"
    elif intent == TRACK_ORDER or ("طلب" in normalized_text and ("اتابع" in normalized_text or "متابعه" in normalized_text)):
        await _set_state(db, phone, "waiting_for_tracking_order_number", now)
        _queue_text(db, phone, "اكتب رقم الطلب الذي تريد متابعته.", window_end)
        result = "tracking_number_requested"
    elif state == "waiting_for_tracking_order_number" and text:
        order = await _order_by_number(db, phone, text)
        if order:
            _queue_text(db, phone, build_order_message(_order_payload(order), "status_changed"), window_end, order_id=order.id, customer_id=order.customer_id)
            await _set_state(db, phone, "idle", now)
            result = "tracking_details_sent"
        else:
            _queue_text(db, phone, "لم نجد طلبًا بهذا الرقم مرتبطًا برقم واتساب الحالي. راجع الرقم وحاول مرة أخرى.", window_end)
            result = "tracking_rejected"
    elif intent == START_ORDER or normalized_text in {"عاوز اطلب", "عايز اطلب", "اطلب"}:
        _queue_text(db, phone, f"تقدر تشوف المنيو وتعمل طلبك من هنا:\n{config.menu_url}", window_end)
        result = "menu_sent"
    elif intent == CUSTOMER_SERVICE or "خدمه العملاء" in normalized_text or "اكلم خدمه" in normalized_text:
        if config.customer_service_phone:
            support = normalize_whatsapp_phone(config.customer_service_phone) or config.customer_service_phone
            _queue_text(db, phone, f"تقدر تكلم خدمة العملاء من هنا:\nhttps://wa.me/{support}", window_end)
        else:
            _queue_text(db, phone, "رقم خدمة العملاء غير متاح حاليًا.", window_end)
        result = "support_sent"
    else:
        _queue_text(
            db, phone,
            "أهلاً بك في توب شيف. اختر من عناصر بدء المحادثة: عاوز أطلب، متابعة طلب، استلام تحديثات، أو خدمة العملاء.",
            window_end,
        )

    inbound.processed_at = datetime.now(UTC).replace(tzinfo=None)
    inbound.processing_result = result
    return result
