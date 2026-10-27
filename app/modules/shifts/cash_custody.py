"""Explicit, auditable custody of restaurant-owned cash.

An order status or a selected payment method is never evidence of collection.
Only a movement into the cashier's custody contributes to confirmed shift cash.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, OrderType, PaymentMethod, UserRole
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.modules.orders.models import Order
from app.modules.shifts.models import CashierShift, OrderCashMovement


ZERO = Decimal("0.00")


def restaurant_due(order: Order) -> Decimal:
    if order.order_status == OrderStatus.CANCELLED or order.is_deleted:
        return ZERO
    amount = Decimal(order.total_amount or 0)
    if order.order_type == OrderType.DELIVERY:
        amount -= Decimal(order.delivery_fee or 0)
    return amount


def balances(movements: list[OrderCashMovement]) -> dict[str, Decimal]:
    result = {"customer_paid": ZERO, "rider_holding": ZERO, "cashier_received": ZERO}
    for movement in movements:
        amount = Decimal(movement.amount)
        if movement.from_holder == "customer":
            result["customer_paid"] += amount
        if movement.to_holder == "customer":
            result["customer_paid"] -= amount
        if movement.to_holder == "rider":
            result["rider_holding"] += amount
        if movement.from_holder == "rider":
            result["rider_holding"] -= amount
        if movement.to_holder == "cashier":
            result["cashier_received"] += amount
        if movement.from_holder == "cashier":
            result["cashier_received"] -= amount
    return result


async def active_shift(db: AsyncSession, cashier_id: int) -> CashierShift:
    shift = await db.scalar(
        select(CashierShift).where(
            CashierShift.user_id == cashier_id, CashierShift.end_time.is_(None)
        ).order_by(CashierShift.id.desc())
    )
    if not shift:
        raise ValidationError("لا يوجد شيفت مفتوح للكاشير")
    if getattr(shift, "cash_tracking_enabled", False) and getattr(shift, "opening_confirmed_at", None) is None:
        raise ValidationError("أكد عدّ عهدة بداية الشيفت قبل تسجيل التحصيل")
    return shift


async def movement_summary(db: AsyncSession, order: Order) -> dict:
    movements = (await db.execute(
        select(OrderCashMovement).where(OrderCashMovement.order_id == order.id)
        .order_by(OrderCashMovement.id)
    )).scalars().all()
    amounts = balances(movements)
    due = restaurant_due(order)
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "restaurant_due": due,
        "customer_paid": amounts["customer_paid"],
        "rider_holding": amounts["rider_holding"],
        "cashier_received": amounts["cashier_received"],
        "uncollected": max(ZERO, due - amounts["customer_paid"]),
        "over_collected": max(ZERO, amounts["customer_paid"] - due),
        "movements": movements,
    }


async def _existing_key(db: AsyncSession, key: str, order_id: int, from_holder: str, to_holder: str, amount: Decimal):
    existing = await db.scalar(select(OrderCashMovement).where(OrderCashMovement.idempotency_key == key))
    if existing:
        if (existing.order_id, existing.from_holder, existing.to_holder, existing.amount) != (
            order_id, from_holder, to_holder, amount
        ):
            raise ValidationError("مفتاح العملية مستخدم لحركة نقدية مختلفة")
    return existing


async def _locked_order(db: AsyncSession, order_id: int) -> Order:
    order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise NotFoundError("Order")
    if order.is_deleted or order.order_status == OrderStatus.CANCELLED:
        raise ValidationError("لا يمكن تسجيل تحصيل لطلب ملغي")
    if order.payment_method != PaymentMethod.CASH:
        raise ValidationError("الطلب ليس نقديًا")
    return order


async def record_customer_collection(
    db: AsyncSession, order_id: int, actor, key: str, note: str | None = None,
    *, initial_shift: CashierShift | None = None,
) -> OrderCashMovement:
    order = await _locked_order(db, order_id)
    due = restaurant_due(order)
    if due <= ZERO:
        raise ValidationError("لا يوجد مبلغ نقدي مستحق للمطعم")
    if actor.role == UserRole.DELIVERY:
        if order.order_type != OrderType.DELIVERY or order.delivery_person_id != actor.id:
            raise AuthorizationError("الطلب غير مسند لهذا المندوب")
        holder, shift_id, rider_id = "rider", None, actor.id
    elif actor.role == UserRole.CASHIER:
        if order.order_type == OrderType.DELIVERY:
            raise ValidationError("تحصيل الدليفري يؤكده المندوب أولًا")
        shift = initial_shift or await active_shift(db, actor.id)
        holder, shift_id, rider_id = "cashier", shift.id, None
    else:
        raise AuthorizationError("تأكيد تحصيل العميل للكاشير أو المندوب فقط")
    existing = await _existing_key(db, key, order.id, "customer", holder, due)
    if existing:
        return existing
    summary = await movement_summary(db, order)
    if summary["customer_paid"] != ZERO:
        raise ValidationError("تحصيل العميل مسجل بالفعل؛ راجع سجل الحركات")
    movement = OrderCashMovement(
        order_id=order.id, shift_id=shift_id, rider_id=rider_id, actor_id=actor.id,
        from_holder="customer", to_holder=holder, amount=due,
        note=note, idempotency_key=key,
    )
    db.add(movement)
    await db.flush()
    return movement


async def record_rider_handoff(
    db: AsyncSession, order_id: int, cashier, amount: Decimal, key: str, note: str | None = None,
) -> OrderCashMovement:
    if cashier.role != UserRole.CASHIER:
        raise AuthorizationError("الكاشير فقط يؤكد استلام النقد من المندوب")
    order = await _locked_order(db, order_id)
    if order.order_type != OrderType.DELIVERY or not order.delivery_person_id:
        raise ValidationError("الطلب ليس دليفري مسندًا لمندوب")
    shift = await active_shift(db, cashier.id)
    existing = await _existing_key(db, key, order.id, "rider", "cashier", amount)
    if existing:
        return existing
    summary = await movement_summary(db, order)
    if amount <= ZERO or amount > summary["rider_holding"]:
        raise ValidationError("المبلغ أكبر من عهدة المندوب المسجلة لهذا الطلب")
    movement = OrderCashMovement(
        order_id=order.id, shift_id=shift.id, rider_id=order.delivery_person_id,
        actor_id=cashier.id, from_holder="rider", to_holder="cashier",
        amount=amount, note=note, idempotency_key=key,
    )
    db.add(movement)
    await db.flush()
    return movement


async def reverse_movement(db: AsyncSession, movement_id: int, admin, key: str, reason: str) -> OrderCashMovement:
    if admin.role != UserRole.ADMIN:
        raise AuthorizationError("الإدارة فقط تسجل رد النقد أو تصحيح التحصيل")
    original = await db.get(OrderCashMovement, movement_id)
    if not original:
        raise NotFoundError("Cash movement")
    await db.scalar(select(Order.id).where(Order.id == original.order_id).with_for_update())
    existing = await _existing_key(
        db, key, original.order_id, original.to_holder, original.from_holder, Decimal(original.amount)
    )
    if existing:
        return existing
    reversed_row = await db.scalar(
        select(OrderCashMovement).where(OrderCashMovement.reversal_of_id == original.id)
    )
    if reversed_row or original.reversal_of_id:
        raise ValidationError("الحركة مصححة بالفعل أو هي حركة تصحيح")
    order = await db.get(Order, original.order_id)
    summary = await movement_summary(db, order)
    if original.to_holder == "rider" and summary["rider_holding"] < original.amount:
        raise ValidationError("يجب تصحيح تسليم المندوب للكاشير قبل رد تحصيل العميل")
    movement = OrderCashMovement(
        order_id=original.order_id, shift_id=original.shift_id, rider_id=original.rider_id,
        actor_id=admin.id, from_holder=original.to_holder, to_holder=original.from_holder,
        amount=original.amount, note=reason, idempotency_key=key, reversal_of_id=original.id,
    )
    db.add(movement)
    await db.flush()
    return movement


async def assert_financial_change_clear(db: AsyncSession, order: Order) -> None:
    count = await db.scalar(select(OrderCashMovement.id).where(OrderCashMovement.order_id == order.id).limit(1))
    if count:
        summary = await movement_summary(db, order)
        if summary["customer_paid"] or summary["rider_holding"] or summary["cashier_received"]:
            raise ValidationError("صحح أو رد التحصيل المسجل أولًا قبل تغيير قيمة الطلب أو إلغائه")
