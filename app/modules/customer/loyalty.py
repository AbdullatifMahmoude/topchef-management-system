"""Award points once per confirmed order and reverse them on cancellation."""
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import OrderStatus
from app.core.exceptions import AuthenticationError, ValidationError
from app.modules.customer.models import Customer, CustomerDevice, CustomerPointLedger
from app.modules.customer.phone import normalize_egyptian_phone
from app.modules.menu.models import Product
from app.modules.orders.models import Order
from app.modules.settings.schemas import (
    LoyaltySettingsResponse,
    LoyaltySettingsUpdate,
    LoyaltyTier,
)
from app.modules.settings.service import SettingsService

CAIRO = ZoneInfo("Africa/Cairo")


def points_month_bounds(now: datetime | None = None) -> tuple[datetime, datetime, datetime, datetime]:
    """Return [start, end) in UTC and in local Cairo time for the current calendar month."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("points_month_bounds requires an aware datetime")
    local = instant.astimezone(CAIRO)
    start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local.replace(
        year=start_local.year + 1, month=1,
    ) if start_local.month == 12 else start_local.replace(month=start_local.month + 1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC), start_local, end_local


@dataclass
class RedemptionSelection:
    rule_id: str
    reward_type: str
    points_required: int
    reward_value: Decimal
    selected_at: datetime
    product_id: int | None = None
    product_name: str | None = None
    variant_name: str | None = None


async def select_redemption(db: AsyncSession, rule_id: str, payload: dict, phone: str | None) -> RedemptionSelection:
    customer_id = payload["customer_id"]
    customer = await db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
    selected_at = datetime.now(UTC)
    device = await db.get(CustomerDevice, payload.get("device_id")) if payload.get("device_id") else None
    if (
        not customer or customer.is_deleted or not customer.pin_hash or not customer.account_activated_at
        or not phone or normalize_egyptian_phone(phone) != normalize_egyptian_phone(customer.phone_number)
        or not device or device.customer_id != customer_id or device.revoked_at is not None
        or device.expires_at <= datetime.now(UTC).replace(tzinfo=None)
    ):
        raise AuthenticationError("الحساب المسجل لا يطابق بيانات الطلب")
    config = await SettingsService(db).get_loyalty_settings()
    rule = next((item for item in config.redemption_rules if str(item.id) == rule_id), None)
    if not config.redemption_active or not rule:
        raise ValidationError("مكافأة النقاط لم تعد متاحة")
    if await customer_points_balance(db, customer_id, now=selected_at) < rule.points_required:
        raise ValidationError("رصيد النقاط غير كافٍ لهذه المكافأة في الشهر الحالي. النقاط غير المستبدلة تنتهي أول كل شهر بتوقيت القاهرة")
    if rule.reward_type == "fixed_discount":
        return RedemptionSelection(rule_id, rule.reward_type, rule.points_required, rule.discount_amount, selected_at)
    product = await db.scalar(select(Product).where(Product.id == rule.product_id).options(
        selectinload(Product.variants), selectinload(Product.category),
    ))
    if not product or product.is_deleted or not product.is_available or not product.category \
            or not product.category.is_active or product.category.is_deleted:
        raise ValidationError("الصنف المجاني لم يعد متاحًا")
    variant = next((item for item in product.variants if item.id == rule.variant_id and not item.is_deleted), None)
    if not variant or Decimal(variant.price) <= 0:
        raise ValidationError("حجم الصنف المجاني لم يعد متاحًا")
    return RedemptionSelection(
        rule_id, rule.reward_type, rule.points_required, Decimal(variant.price),
        selected_at, product.id, product.product_name, variant.name,
    )


def calculate_points(amount: Decimal, tiers: list[LoyaltyTier], max_points: int) -> int:
    """Apply each tier only to its slice; incomplete steps earn no points."""
    total = 0
    for index, tier in enumerate(tiers):
        upper = tiers[index + 1].from_amount if index + 1 < len(tiers) else amount
        slice_amount = max(Decimal(0), min(amount, upper) - tier.from_amount)
        total += int(slice_amount // tier.step_amount) * tier.points_per_step
        if total >= max_points:
            return max_points
    return total


async def award_order_points(db: AsyncSession, order: Order) -> bool:
    if order.order_status != OrderStatus.CONFIRMED or not order.customer_id:
        return False
    config: LoyaltySettingsResponse = await SettingsService(db).get_loyalty_settings()
    if not config.active:
        return False
    customer = await db.get(Customer, order.customer_id)
    if (
        not customer or customer.is_deleted or not customer.pin_hash
        or not customer.account_activated_at
        or not order.customer_phone
        or normalize_egyptian_phone(order.customer_phone) != normalize_egyptian_phone(customer.phone_number)
    ):
        return False
    amount = max(Decimal(0), Decimal(order.subtotal) - Decimal(order.discount_amount))
    points = calculate_points(amount, config.tiers, config.max_points_per_order) if amount >= config.minimum_order_amount else 0
    if await db.scalar(select(CustomerPointLedger.id).where(CustomerPointLedger.order_id == order.id)):
        return False
    db.add(CustomerPointLedger(
        customer_id=customer.id, order_id=order.id, points=points, eligible_amount=amount,
        rules_snapshot=config.model_dump_json(), created_at=datetime.now(UTC).replace(tzinfo=None),
    ))
    await db.flush()
    return True


async def recalculate_order_points(db: AsyncSession, order: Order) -> bool:
    award = await db.scalar(
        select(CustomerPointLedger).where(CustomerPointLedger.order_id == order.id).with_for_update()
    )
    if not award or award.reversed_at is not None:
        return False
    config = LoyaltySettingsUpdate.model_validate(json.loads(award.rules_snapshot))
    amount = max(Decimal(0), Decimal(order.subtotal) - Decimal(order.discount_amount))
    customer = await db.get(Customer, order.customer_id) if order.customer_id else None
    eligible_customer = bool(
        customer and not customer.is_deleted and customer.pin_hash and customer.account_activated_at
        and order.customer_phone
        and normalize_egyptian_phone(order.customer_phone) == normalize_egyptian_phone(customer.phone_number)
    )
    award.eligible_amount = amount
    award.points = (
        calculate_points(amount, config.tiers, config.max_points_per_order)
        if eligible_customer and amount >= config.minimum_order_amount else 0
    )
    if eligible_customer:
        award.customer_id = customer.id
    await db.flush()
    return True


async def reverse_order_points(db: AsyncSession, order_id: int) -> bool:
    award = await db.scalar(
        select(CustomerPointLedger).where(CustomerPointLedger.order_id == order_id).with_for_update()
    )
    if not award or award.reversed_at is not None:
        return False
    award.reversed_at = datetime.now(UTC).replace(tzinfo=None)
    await db.flush()
    return True


async def customer_points_balance(db: AsyncSession, customer_id: int, *, now: datetime | None = None) -> int:
    start_utc, end_utc, start_local, end_local = points_month_bounds(now)
    value = await db.scalar(select(func.coalesce(func.sum(CustomerPointLedger.points), 0)).where(
        CustomerPointLedger.customer_id == customer_id,
        CustomerPointLedger.reversed_at.is_(None),
        CustomerPointLedger.created_at >= start_utc.replace(tzinfo=None),
        CustomerPointLedger.created_at < end_utc.replace(tzinfo=None),
    ))
    spent = await db.scalar(select(func.coalesce(func.sum(Order.loyalty_points_spent), 0)).where(
        Order.customer_id == customer_id,
        Order.loyalty_status.in_(("reserved", "consumed")),
        or_(
            and_(Order.loyalty_reserved_at >= start_utc.replace(tzinfo=None),
                 Order.loyalty_reserved_at < end_utc.replace(tzinfo=None)),
            and_(Order.loyalty_reserved_at.is_(None),
                 Order.created_at >= start_local.replace(tzinfo=None),
                 Order.created_at < end_local.replace(tzinfo=None)),
        ),
    ))
    return max(0, int(value or 0) - int(spent or 0))
