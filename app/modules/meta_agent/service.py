from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus
from app.modules.customer.phone import normalize_egyptian_phone
from app.modules.menu.models import Category, Product, Variant
from app.modules.meta_agent.schemas import (
    MenuProduct,
    MenuResponse,
    MenuVariant,
    OrderStatusEvent,
    OrderTrackingResponse,
)
from app.modules.orders.models import Order, OrderStatusHistory

STATUS_LABELS = {
    OrderStatus.NEW: "جديد",
    OrderStatus.CONFIRMED: "تم التأكيد",
    OrderStatus.OUT_FOR_DELIVERY: "خرج للتوصيل",
    OrderStatus.COMPLETED: "مكتمل",
    OrderStatus.DELIVERED: "تم التسليم",
    OrderStatus.CANCELLED: "ملغي",
}


def _status_value(status: OrderStatus | str) -> str:
    return status.value if isinstance(status, OrderStatus) else str(status).lower()


def _status_label(status: OrderStatus | str) -> str:
    if isinstance(status, OrderStatus):
        return STATUS_LABELS.get(status, status.value)
    try:
        return STATUS_LABELS.get(OrderStatus(status), str(status))
    except ValueError:
        return str(status)


async def get_available_menu(db: AsyncSession) -> MenuResponse:
    result = await db.execute(
        select(
            Product.id.label("product_id"),
            Product.product_name,
            Product.description,
            Category.cat_name,
            Variant.id.label("variant_id"),
            Variant.name.label("variant_name"),
            Variant.price,
        )
        .join(Category, Category.id == Product.cat_id)
        .join(Variant, Variant.product_id == Product.id)
        .where(
            Category.is_active.is_(True),
            Category.is_deleted.is_(False),
            Product.is_available.is_(True),
            Product.is_deleted.is_(False),
            Variant.is_deleted.is_(False),
        )
        .order_by(Category.cat_name, Product.product_name, Variant.price, Variant.name)
    )
    products_by_id: dict[int, MenuProduct] = {}
    for row in result.all():
        product = products_by_id.get(row.product_id)
        if product is None:
            product = MenuProduct(
                id=row.product_id,
                name=row.product_name,
                description=row.description,
                category=row.cat_name,
                variants=[],
            )
            products_by_id[row.product_id] = product
        product.variants.append(
            MenuVariant(id=row.variant_id, name=row.variant_name, price=row.price)
        )
    return MenuResponse(products=list(products_by_id.values()))


async def get_owned_order_status(
    db: AsyncSession,
    *,
    order_number: str,
    customer_phone: str,
) -> OrderTrackingResponse | None:
    clean_number = order_number.strip().lstrip("#")
    normalized_phone = normalize_egyptian_phone(customer_phone)
    if not clean_number or len(normalized_phone) != 11 or not normalized_phone.startswith("01"):
        return None

    result = await db.execute(
        select(
            Order.id,
            Order.order_number,
            Order.customer_phone,
            Order.order_status,
            Order.updated_at,
        )
        .where(Order.order_number == clean_number, Order.is_deleted.is_(False))
        .order_by(Order.created_at.desc())
        .limit(20)
    )
    order = next(
        (
            candidate
            for candidate in result.all()
            if normalize_egyptian_phone(candidate.customer_phone) == normalized_phone
        ),
        None,
    )
    if order is None:
        return None

    history_result = await db.execute(
        select(OrderStatusHistory.status, OrderStatusHistory.changed_at)
        .where(
            OrderStatusHistory.order_id == order.id,
            OrderStatusHistory.is_deleted.is_(False),
        )
        .order_by(OrderStatusHistory.changed_at)
    )
    history = [
        OrderStatusEvent(
            status=_status_value(event.status),
            status_label=_status_label(event.status),
            changed_at=event.changed_at,
        )
        for event in history_result.all()
    ]
    return OrderTrackingResponse(
        order_number=order.order_number,
        status=_status_value(order.order_status),
        status_label=_status_label(order.order_status),
        updated_at=order.updated_at,
        history=history,
    )
