import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import get_db
from app.core.enums import OrderStatus, OrderType, PaymentMethod, UserRole
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.redis import get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.orders.models import Order
from app.modules.shifts import cash_custody
from app.modules.shifts.models import (
    CashierShift,
    OrderCashMovement,
    ShiftCashAdjustment,
    ShiftCloseSnapshot,
    ShiftExpenseAudit,
)
from app.modules.shifts.service import (
    ShiftsService,
    get_business_date,
    is_approved_cutover_shift,
)
from app.modules.users.models import User

router = APIRouter(prefix="/shifts", tags=["shifts"])

class ShiftCashUpdate(BaseModel):
    opening_cash: Decimal | None = Field(default=None, ge=0)
    actual_closing_cash: Decimal | None = Field(default=None, ge=0)
    closing_note: str | None = Field(default=None, max_length=500)

class ExpenseCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    amount: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)
    receipt_reference: str | None = Field(default=None, max_length=200)

class AdminExpenseCreate(ExpenseCreate):
    target_date: date
    shift_id: int = Field(gt=0)
    paid_from: str = Field(pattern="^(shift_cash|admin_cash)$")

class AdminExpenseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)
    target_date: date | None = None
    shift_id: int | None = Field(default=None, gt=0)
    paid_from: str | None = Field(default=None, pattern="^(shift_cash|admin_cash)$")
    receipt_reference: str | None = Field(default=None, max_length=200)


class CashCollectionCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class RiderHandoffCreate(CashCollectionCreate):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class CashReversalCreate(CashCollectionCreate):
    reason: str = Field(min_length=3, max_length=500)


class ShiftCloseConfirmation(BaseModel):
    admin_count: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)


class ShiftCashAdjustmentCreate(BaseModel):
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=100)


def _cash_movement_payload(row: OrderCashMovement) -> dict:
    return {
        "id": row.id, "order_id": row.order_id, "shift_id": row.shift_id,
        "rider_id": row.rider_id, "actor_id": row.actor_id,
        "from_holder": row.from_holder, "to_holder": row.to_holder,
        "amount": float(row.amount), "note": row.note,
        "reversal_of_id": row.reversal_of_id, "created_at": row.created_at.isoformat(),
    }


def _expense_values(expense) -> dict:
    return {
        "shift_id": expense.shift_id, "target_date": expense.target_date.isoformat(),
        "title": expense.title, "amount": str(expense.amount),
        "paid_from": expense.paid_from, "receipt_reference": expense.receipt_reference,
        "note": expense.note, "is_deleted": expense.is_deleted,
    }


def _audit_expense(db: AsyncSession, expense, actor_id: int, action: str, before: dict | None = None) -> None:
    db.add(ShiftExpenseAudit(
        expense_id=expense.id, actor_id=actor_id, action=action,
        before_values=before, after_values=_expense_values(expense),
    ))


@router.get("/cash/orders/{order_id}")
async def get_order_cash_status(
    order_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    order = await db.get(Order, order_id)
    if not order:
        raise NotFoundError("Order")
    if current_user.role not in (UserRole.ADMIN, UserRole.CASHIER, UserRole.DELIVERY):
        raise AuthorizationError("غير مصرح بعرض تفاصيل تحصيل الطلب")
    if current_user.role == UserRole.CASHIER and order.created_by_user_id != current_user.id:
        raise AuthorizationError("لا يمكنك عرض تحصيل طلب كاشير آخر")
    if current_user.role == UserRole.DELIVERY and order.delivery_person_id != current_user.id:
        raise AuthorizationError("الطلب غير مسند لهذا المندوب")
    summary = await cash_custody.movement_summary(db, order)
    available = await cash_custody.cash_collection_available(db, order)
    return {
        **{key: float(value) if isinstance(value, Decimal) else value for key, value in summary.items() if key != "movements"},
        "cash_tracking_enabled": bool(order.cash_tracking_enabled),
        "cash_collection_available": available,
        "legacy_same_shift": available and not order.cash_tracking_enabled,
        "movements": [_cash_movement_payload(row) for row in summary["movements"]],
    }


@router.post("/cash/orders/{order_id}/customer-collection")
async def confirm_customer_cash(
    order_id: int, payload: CashCollectionCreate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    row = await cash_custody.record_customer_collection(
        db, order_id, current_user, payload.idempotency_key, payload.note,
    )
    await db.commit()
    return _cash_movement_payload(row)


@router.post("/cash/orders/{order_id}/rider-handoff")
async def confirm_rider_handoff(
    order_id: int, payload: RiderHandoffCreate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    row = await cash_custody.record_rider_handoff(
        db, order_id, current_user, payload.amount, payload.idempotency_key, payload.note,
    )
    await db.commit()
    return _cash_movement_payload(row)


@router.post("/cash/orders/{order_id}/direct-rider-settlement")
async def confirm_direct_rider_settlement(
    order_id: int, payload: RiderHandoffCreate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    row = await cash_custody.record_direct_rider_settlement(
        db, order_id, current_user, payload.amount, payload.idempotency_key,
    )
    await db.commit()
    return _cash_movement_payload(row)


@router.post("/cash/movements/{movement_id}/reverse")
async def reverse_cash_movement(
    movement_id: int, payload: CashReversalCreate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    row = await cash_custody.reverse_movement(
        db, movement_id, current_user, payload.idempotency_key, payload.reason,
    )
    await db.commit()
    return _cash_movement_payload(row)


@router.get("/cash/riders/outstanding")
async def rider_cash_outstanding(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role not in (UserRole.ADMIN, UserRole.CASHIER, UserRole.DELIVERY):
        raise AuthorizationError("غير مصرح بعرض عهدة المندوبين")
    signed_rider_amount = case(
        (OrderCashMovement.to_holder == "rider", OrderCashMovement.amount),
        else_=-OrderCashMovement.amount,
    )
    query = (
        select(OrderCashMovement.rider_id, User.full_name, Order.id, Order.order_number,
               func.sum(signed_rider_amount).label("balance"))
        .join(Order, Order.id == OrderCashMovement.order_id)
        .join(User, User.id == OrderCashMovement.rider_id)
        .where(OrderCashMovement.rider_id.is_not(None))
        .group_by(OrderCashMovement.rider_id, User.full_name, Order.id)
        .having(func.sum(signed_rider_amount) > 0)
        .order_by(OrderCashMovement.rider_id, Order.id)
    )
    if current_user.role == UserRole.DELIVERY:
        query = query.where(OrderCashMovement.rider_id == current_user.id)
    rows = (await db.execute(query)).all()
    return [{"rider_id": rider_id, "rider_name": rider_name, "order_id": order_id, "order_number": order_number,
             "restaurant_cash_due_from_rider": float(balance)}
            for rider_id, rider_name, order_id, order_number, balance in rows]


@router.get("/cash/riders/pending-direct-settlement")
async def rider_cash_pending_direct_settlement(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role not in (UserRole.ADMIN, UserRole.CASHIER):
        raise AuthorizationError("الكاشير والإدارة فقط يعرضان التسويات المباشرة")
    has_movements = select(OrderCashMovement.id).where(
        OrderCashMovement.order_id == Order.id,
    ).exists()
    active_shifts = (await db.execute(select(CashierShift).where(
        CashierShift.end_time.is_(None),
    ))).scalars().all()
    active_shifts = [shift for shift in active_shifts if shift.target_date == get_business_date()
                     or is_approved_cutover_shift(shift)]
    active_shifts = [shift for shift in active_shifts if not shift.cash_tracking_enabled and await ShiftsService(db).shift_uses_cash_ledger(shift)]
    legacy_in_shift = or_(*(
        and_(
            Order.cash_tracking_enabled == False,
            Order.created_by_user_id == shift.user_id,
            Order.created_at >= cash_custody.shift_local_time(shift.start_time),
            Order.created_at < cash_custody.shift_local_time(datetime.now(UTC)),
        ) for shift in active_shifts
    )) if active_shifts else False
    rows = (await db.execute(select(
        Order.delivery_person_id, User.full_name, Order.id, Order.order_number,
        (Order.total_amount - Order.delivery_fee).label("due"),
    ).outerjoin(User, User.id == Order.delivery_person_id).where(
        or_(Order.cash_tracking_enabled == True, legacy_in_shift),
        Order.is_deleted == False,
        Order.order_type == OrderType.DELIVERY,
        Order.payment_method == PaymentMethod.CASH,
        Order.order_status.in_((OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED)),
        or_(Order.delivery_person_id.is_not(None), and_(legacy_in_shift, Order.order_status == OrderStatus.DELIVERED)),
        Order.total_amount > Order.delivery_fee,
        ~has_movements,
    ).order_by(Order.id.desc()))).all()
    return [{"rider_id": rider_id, "rider_name": rider_name or "مندوب غير مسند في النظام", "order_id": order_id, "order_number": number,
             "restaurant_cash_due_from_rider": float(due)}
            for rider_id, rider_name, order_id, number, due in rows]


@router.post("/{shift_id}/confirm-close")
async def confirm_shift_close(
    shift_id: int, payload: ShiftCloseConfirmation,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("الإدارة فقط تعتمد تسليم الشيفت")
    shift = await db.scalar(select(CashierShift).where(CashierShift.id == shift_id).with_for_update())
    snapshot = await db.scalar(
        select(ShiftCloseSnapshot).where(ShiftCloseSnapshot.shift_id == shift_id).with_for_update()
    )
    if not shift or not snapshot or shift.end_time is None:
        raise ValidationError("الشيفت لم يُقفل بتسوية محفوظة")
    if snapshot.cashier_count is None:
        raise ValidationError("الكاشير لم يسجل عدّ النقد؛ لا يمكن اعتماد التسليم قبل استكماله")
    if snapshot.confirmed_at:
        raise ValidationError("تسليم الشيفت معتمد بالفعل")
    if payload.admin_count != snapshot.cashier_count and not (payload.note or "").strip():
        raise ValidationError("اذكر سبب اختلاف عدّ الإدارة عن عدّ الكاشير")
    snapshot.admin_id = current_user.id
    snapshot.admin_count = payload.admin_count
    snapshot.confirmed_at = datetime.now(UTC)
    snapshot.confirmation_note = (payload.note or "").strip() or None
    await db.commit()
    return {
        "shift_id": shift_id, "cashier_count": float(snapshot.cashier_count),
        "admin_count": float(snapshot.admin_count),
        "count_difference": float(snapshot.admin_count - snapshot.cashier_count),
        "confirmed_at": snapshot.confirmed_at.isoformat(),
    }


@router.post("/{shift_id}/post-close-adjustments")
async def record_post_close_adjustment(
    shift_id: int, payload: ShiftCashAdjustmentCreate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("الإدارة فقط تسجل تسوية بعد الإقفال")
    shift = await db.scalar(select(CashierShift).where(CashierShift.id == shift_id).with_for_update())
    if not shift or shift.end_time is None:
        raise ValidationError("التسوية اللاحقة تتطلب شيفتًا مغلقًا")
    if not await ShiftsService(db).shift_uses_cash_ledger(shift):
        raise ValidationError("الشيفت قديم؛ استخدم إضافة العهدة التاريخية")
    if payload.amount == 0:
        raise ValidationError("مبلغ التسوية لا يمكن أن يكون صفرًا")
    existing = await db.scalar(select(ShiftCashAdjustment).where(
        ShiftCashAdjustment.idempotency_key == payload.idempotency_key
    ))
    if existing:
        if existing.shift_id != shift_id or existing.amount != payload.amount or existing.reason != payload.reason.strip():
            raise ValidationError("مفتاح التسوية مستخدم لعملية مختلفة")
        return {"id": existing.id, "shift_id": existing.shift_id, "amount": float(existing.amount),
                "reason": existing.reason, "actor_id": existing.actor_id, "created_at": existing.created_at.isoformat()}
    row = ShiftCashAdjustment(
        shift_id=shift_id, actor_id=current_user.id,
        amount=payload.amount, reason=payload.reason.strip(), idempotency_key=payload.idempotency_key,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "shift_id": row.shift_id, "amount": float(row.amount),
            "reason": row.reason, "actor_id": row.actor_id, "created_at": row.created_at.isoformat()}

class CashAdditionCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=2, max_length=500)

async def _current_shift(db: AsyncSession, user_id: int, redis):
    return await ShiftsService(db, redis).start_shift(user_id, sync_web_orders=True)

async def _expense_totals(db: AsyncSession, shift_id: int, target_date: date) -> tuple[Decimal, Decimal]:
    from app.modules.shifts.models import ShiftExpense
    shift = await db.get(CashierShift, shift_id)
    shift_total = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.shift_id == shift_id,
        ShiftExpense.is_deleted == False,
        *((ShiftExpense.paid_from == "shift_cash",) if shift and shift.cash_tracking_enabled else ()),
    )) or Decimal(0)
    day_total = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.target_date == target_date,
        ShiftExpense.is_deleted == False,
    )) or Decimal(0)
    return shift_total, day_total

@router.get("/current/cash")
async def get_current_shift_cash(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can view the current shift")
    shift = await _current_shift(db, current_user.id, redis)
    if not shift:
        return {"active": False}
    ledger_mode = await ShiftsService(db).shift_uses_cash_ledger(shift)
    from app.modules.shifts.models import ShiftExpense
    expenses = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.shift_id == shift.id,
        ShiftExpense.is_deleted == False,
        *((ShiftExpense.paid_from == "shift_cash",) if shift.cash_tracking_enabled else ()),
    )) or Decimal(0)
    return {
        "active": True,
        "shift_id": shift.id,
        "target_date": shift.target_date.isoformat(),
        "stale_shift": shift.target_date != get_business_date(),
        "opening_cash": float(shift.opening_cash or 0),
        "opening_confirmed": bool(shift.opening_confirmed_at) if ledger_mode else True,
        "cash_tracking_enabled": ledger_mode,
        "actual_closing_cash": float(shift.actual_closing_cash) if shift.actual_closing_cash is not None else None,
        "closing_note": shift.closing_note or "",
        "expenses_total": float(expenses),
    }

@router.patch("/current/cash")
async def update_current_shift_cash(
    payload: ShiftCashUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can reconcile the current shift")
    shift = await _current_shift(db, current_user.id, redis)
    if not shift:
        raise ValidationError("لا يوجد شيفت نشط لتسويته")
    ledger_mode = await ShiftsService(db).shift_uses_cash_ledger(shift)
    changes = payload.model_dump(exclude_unset=True)
    if "opening_cash" in changes and changes["opening_cash"] is None:
        raise ValidationError("عهدة بداية الشيفت لا يمكن تركها فارغة")
    if "opening_cash" in changes and changes["opening_cash"] is not None:
        if ledger_mode and shift.opening_confirmed_at and changes["opening_cash"] != shift.opening_cash:
            raise ValidationError("بعد تأكيد عهدة البداية، لا تُعدل قيمتها؛ اطلب تصحيحًا موثقًا من الإدارة")
        shift.opening_confirmed_at = datetime.now(UTC)
    for field, value in changes.items():
        setattr(shift, field, value)
    await db.commit()
    return {"message": "Shift cash updated", "shift_id": shift.id}


@router.get("/current/reconciliation")
async def current_reconciliation(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("الكاشير فقط يعرض تسوية شيفته")
    shift = await _current_shift(db, current_user.id, redis)
    if not shift:
        return {"active": False}
    report = await ShiftsService(db).get_shifts_report(shift.target_date)
    return next(item for item in report if item["id"] == shift.id)

@router.get("/current/expenses")
async def list_current_expenses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can view shift expenses")
    shift = await _current_shift(db, current_user.id, redis)
    if not shift:
        return {"shift_id": None, "total": 0, "items": []}
    from app.modules.shifts.models import ShiftExpense
    rows = (await db.execute(select(ShiftExpense).where(
        ShiftExpense.shift_id == shift.id,
        ShiftExpense.is_deleted == False,
        *((ShiftExpense.paid_from == "shift_cash",) if shift.cash_tracking_enabled else ()),
    ).order_by(desc(ShiftExpense.id)))).scalars().all()
    return {
        "shift_id": shift.id,
        "total": float(sum((row.amount or 0) for row in rows)),
        "items": [{"id": row.id, "title": row.title, "amount": float(row.amount), "note": row.note, "receipt_reference": row.receipt_reference, "paid_from": row.paid_from, "created_at": row.created_at.isoformat(), "can_delete": row.user_id == current_user.id} for row in rows],
    }

@router.post("/current/expenses")
async def create_current_expense(
    payload: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can add shift expenses")
    shift = await _current_shift(db, current_user.id, redis)
    if not shift:
        raise ValidationError("لا يوجد شيفت نشط لتسجيل المصروف")
    if shift.target_date != get_business_date():
        raise ValidationError("الشيفت من يوم عمل سابق؛ أكمل العدّ والتسليم قبل تسجيل مصروفات جديدة")
    ledger_mode = await ShiftsService(db).shift_uses_cash_ledger(shift)
    if ledger_mode and shift.opening_confirmed_at is None:
        raise ValidationError("أكد عدّ عهدة بداية الشيفت قبل تسجيل المصروف")
    from app.modules.shifts.models import ShiftExpense
    expense = ShiftExpense(shift_id=shift.id, user_id=current_user.id, target_date=shift.target_date, title=payload.title.strip(), amount=payload.amount, note=payload.note.strip() if payload.note else None, receipt_reference=payload.receipt_reference, paid_from="shift_cash")
    db.add(expense)
    if ledger_mode:
        await db.flush()
        _audit_expense(db, expense, current_user.id, "created")
    await db.commit()
    await db.refresh(expense)
    shift_total, day_total = await _expense_totals(db, shift.id, shift.target_date)
    from app.core.events import order_events_manager
    asyncio.create_task(order_events_manager.emit({"type": "EXPENSE_UPDATED", "data": {"shift_id": shift.id, "target_date": shift.target_date.isoformat(), "shift_total": float(shift_total), "day_total": float(day_total)}}))
    return {
        "id": expense.id,
        "title": expense.title,
        "amount": float(expense.amount),
        "note": expense.note,
        "paid_from": expense.paid_from,
        "receipt_reference": expense.receipt_reference,
        "created_at": expense.created_at.isoformat(),
        "can_delete": True,
        "shift_total": float(shift_total),
        "day_total": float(day_total),
    }

@router.delete("/current/expenses/{expense_id}")
async def delete_current_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can delete shift expenses")
    from app.modules.shifts.models import ShiftExpense
    shift = await _current_shift(db, current_user.id, redis)
    expense = await db.scalar(select(ShiftExpense).where(ShiftExpense.id == expense_id, ShiftExpense.user_id == current_user.id, ShiftExpense.shift_id == (shift.id if shift else -1), ShiftExpense.is_deleted == False))
    if not expense:
        raise NotFoundError("Expense")
    before = _expense_values(expense) if shift and await ShiftsService(db).shift_uses_cash_ledger(shift) else None
    expense.is_deleted = True
    if before is not None:
        _audit_expense(db, expense, current_user.id, "deleted", before)
    await db.commit()
    shift_total, day_total = await _expense_totals(db, expense.shift_id, expense.target_date)
    from app.core.events import order_events_manager
    asyncio.create_task(order_events_manager.emit({"type": "EXPENSE_UPDATED", "data": {"shift_id": expense.shift_id, "target_date": expense.target_date.isoformat(), "shift_total": float(shift_total), "day_total": float(day_total)}}))
    return {"message": "Expense deleted", "shift_total": float(shift_total), "day_total": float(day_total)}

@router.get("")
async def get_shifts(
    target_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can view shifts report")
        
    shifts_service = ShiftsService(db)
    dt = target_date or get_business_date()
    return await shifts_service.get_shifts_report(dt)

@router.get("/business-date")
async def get_shift_business_date(
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can view shifts report")
    return {"business_date": get_business_date().isoformat()}

async def _validated_expense_shift(db: AsyncSession, shift_id: int, target_date: date):
    from app.modules.shifts.models import CashierShift

    shift = await db.get(CashierShift, shift_id)
    owner = await db.get(User, shift.user_id) if shift else None
    if not shift or shift.target_date != target_date or not owner or owner.role != UserRole.CASHIER:
        raise ValidationError("اختر شيفت كاشير مسجل في يوم المصروف")
    return shift, owner


def _admin_expense_payload(expense, recorder: User, owner: User | None = None) -> dict:
    return {
        "id": expense.id,
        "title": expense.title,
        "amount": float(expense.amount),
        "note": expense.note,
        "paid_from": expense.paid_from,
        "receipt_reference": expense.receipt_reference,
        "target_date": expense.target_date.isoformat(),
        "created_at": expense.created_at.isoformat(),
        "recorded_by": recorder.full_name or recorder.username,
        "shift_id": expense.shift_id,
        "shift_owner": (owner.full_name or owner.username) if owner else None,
        "source": "admin" if recorder.role == UserRole.ADMIN else "cashier",
        "editable_date": expense.shift_id is None,
    }


@router.get("/admin/expense-shifts")
async def list_admin_expense_shifts(
    target_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can manage expenses")
    from app.modules.shifts.models import CashierShift

    rows = (await db.execute(
        select(CashierShift, User)
        .join(User, User.id == CashierShift.user_id)
        .where(CashierShift.target_date == target_date, User.role == UserRole.CASHIER)
        .order_by(CashierShift.start_time, CashierShift.id)
    )).all()
    return [{
        "id": shift.id,
        "cashier_name": owner.full_name or owner.username,
        "start_time": shift.start_time.isoformat() if shift.start_time else None,
        "end_time": shift.end_time.isoformat() if shift.end_time else None,
    } for shift, owner in rows]

@router.get("/admin/expenses")
async def list_admin_expenses(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can manage expenses")
    if start_date > end_date:
        raise ValidationError("تاريخ البداية يجب أن يسبق تاريخ النهاية")
    from app.modules.shifts.models import CashierShift, ShiftExpense
    shift_owner = aliased(User)
    rows = (await db.execute(
        select(ShiftExpense, User, shift_owner)
        .join(User, User.id == ShiftExpense.user_id)
        .outerjoin(CashierShift, CashierShift.id == ShiftExpense.shift_id)
        .outerjoin(shift_owner, shift_owner.id == CashierShift.user_id)
        .where(
            ShiftExpense.target_date >= start_date,
            ShiftExpense.target_date <= end_date,
            ShiftExpense.is_deleted == False,
        )
        .order_by(ShiftExpense.target_date.desc(), ShiftExpense.created_at.desc())
    )).all()
    items = [_admin_expense_payload(expense, recorder, owner) for expense, recorder, owner in rows]
    total = sum((expense.amount or Decimal(0)) for expense, _, _ in rows)
    return {"items": items, "count": len(items), "total": float(total)}

@router.post("/admin/expenses")
async def create_admin_expense(
    payload: AdminExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can manage expenses")
    from app.modules.shifts.models import ShiftExpense
    title = payload.title.strip()
    if len(title) < 2:
        raise ValidationError("اسم بند المصروف مطلوب")
    shift, owner = await _validated_expense_shift(db, payload.shift_id, payload.target_date)
    expense = ShiftExpense(
        shift_id=shift.id,
        user_id=current_user.id,
        target_date=payload.target_date,
        title=title,
        amount=payload.amount,
        note=payload.note.strip() if payload.note else None,
        receipt_reference=payload.receipt_reference,
        paid_from=payload.paid_from,
    )
    db.add(expense)
    if await ShiftsService(db).shift_uses_cash_ledger(shift):
        await db.flush()
        _audit_expense(db, expense, current_user.id, "created")
    await db.commit()
    await db.refresh(expense)
    shift_total, day_total = await _expense_totals(db, shift.id, expense.target_date)
    from app.core.events import order_events_manager
    asyncio.create_task(order_events_manager.emit({"type": "EXPENSE_UPDATED", "data": {"shift_id": shift.id, "target_date": expense.target_date.isoformat(), "shift_total": float(shift_total), "day_total": float(day_total)}}))
    return _admin_expense_payload(expense, current_user, owner)

@router.patch("/admin/expenses/{expense_id}")
async def update_admin_expense(
    expense_id: int,
    payload: AdminExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can manage expenses")
    from app.modules.shifts.models import CashierShift, ShiftExpense
    expense = await db.scalar(select(ShiftExpense).where(ShiftExpense.id == expense_id, ShiftExpense.is_deleted == False))
    if not expense:
        raise NotFoundError("Expense")
    original_shift = await db.get(CashierShift, expense.shift_id) if expense.shift_id else None
    original_uses_ledger = bool(original_shift and await ShiftsService(db).shift_uses_cash_ledger(original_shift))
    if original_uses_ledger and original_shift.end_time is not None:
        raise ValidationError("مصروف الشيفت المغلق ثابت؛ سجل تصحيحًا لاحقًا بدل تعديل الأصل")
    before = _expense_values(expense) if original_uses_ledger else None
    changes = payload.model_dump(exclude_unset=True)
    if "paid_from" in changes and changes["paid_from"] is None:
        raise ValidationError("حدد مصدر النقد للمصروف")
    if "target_date" in changes and changes["target_date"] is None:
        raise ValidationError("يوم المصروف مطلوب")
    recorder = await db.get(User, expense.user_id)
    if expense.shift_id is not None and "target_date" in changes and changes["target_date"] != expense.target_date and "shift_id" not in changes:
        raise ValidationError("لا يمكن تغيير يوم مصروف مرتبط بشيفت كاشير")
    owner = None
    if "shift_id" in changes:
        if not recorder or recorder.role != UserRole.ADMIN or changes["shift_id"] is None:
            raise ValidationError("لا يمكن تغيير شيفت مصروف الكاشير")
        target_shift, owner = await _validated_expense_shift(
            db, changes["shift_id"], changes.get("target_date") or expense.target_date,
        )
        if await ShiftsService(db).shift_uses_cash_ledger(target_shift) and target_shift.end_time is not None:
            raise ValidationError("لا تنقل المصروف إلى شيفت مغلق؛ سجل تسوية لاحقة")
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if len(changes["title"]) < 2:
            raise ValidationError("اسم بند المصروف مطلوب")
    for field, value in changes.items():
        if field == "note" and value is not None:
            value = value.strip() or None
        setattr(expense, field, value)
    if before is not None:
        _audit_expense(db, expense, current_user.id, "updated", before)
    await db.commit()
    await db.refresh(expense)
    if expense.shift_id is not None and owner is None:
        shift = await db.get(CashierShift, expense.shift_id)
        owner = await db.get(User, shift.user_id) if shift else None
    from app.core.events import order_events_manager
    asyncio.create_task(order_events_manager.emit({"type": "EXPENSE_UPDATED", "data": {"shift_id": expense.shift_id, "target_date": expense.target_date.isoformat()}}))
    return _admin_expense_payload(expense, recorder, owner)


@router.get("/admin/expenses/{expense_id}/audit")
async def get_expense_audit(
    expense_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("الإدارة فقط تعرض سجل تعديل المصروف")
    rows = (await db.execute(select(ShiftExpenseAudit).where(
        ShiftExpenseAudit.expense_id == expense_id
    ).order_by(ShiftExpenseAudit.id))).scalars().all()
    return [{"id": row.id, "actor_id": row.actor_id, "action": row.action,
             "before": row.before_values, "after": row.after_values,
             "created_at": row.created_at.isoformat()} for row in rows]

@router.delete("/admin/expenses/{expense_id}")
async def delete_admin_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can manage expenses")
    from app.modules.shifts.models import ShiftExpense
    expense = await db.scalar(select(ShiftExpense).where(ShiftExpense.id == expense_id, ShiftExpense.is_deleted == False))
    if not expense:
        raise NotFoundError("Expense")
    shift = await db.get(CashierShift, expense.shift_id) if expense.shift_id else None
    shift_uses_ledger = bool(shift and await ShiftsService(db).shift_uses_cash_ledger(shift))
    if shift_uses_ledger and shift.end_time is not None:
        raise ValidationError("لا تحذف مصروف شيفت مغلق؛ سجل تصحيحًا لاحقًا")
    before = _expense_values(expense) if shift_uses_ledger else None
    expense.is_deleted = True
    if before is not None:
        _audit_expense(db, expense, current_user.id, "deleted", before)
    await db.commit()
    from app.core.events import order_events_manager
    asyncio.create_task(order_events_manager.emit({"type": "EXPENSE_UPDATED", "data": {"shift_id": expense.shift_id, "target_date": expense.target_date.isoformat()}}))
    return {"message": "Expense deleted"}

@router.post("/{shift_id}/cash-additions")
async def create_shift_cash_addition(
    shift_id: int,
    payload: CashAdditionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can add recovered shift cash")

    from app.modules.shifts.models import CashierShift, ShiftCashAddition
    shift = await db.scalar(
        select(CashierShift).where(CashierShift.id == shift_id).with_for_update()
    )
    if not shift:
        raise NotFoundError("Shift")
    if await ShiftsService(db).shift_uses_cash_ledger(shift):
        raise ValidationError("استخدم التسوية اللاحقة للشيفتات ذات سجل التحصيل الجديد")
    if shift.end_time is None:
        raise ValidationError("لا يمكن إضافة مبلغ قبل إغلاق الشيفت")
    if shift.actual_closing_cash is None:
        raise ValidationError("يجب تسجيل النقد الفعلي للشيفت قبل إضافة المبلغ")

    reason = payload.reason.strip()
    if len(reason) < 2:
        raise ValidationError("سبب إضافة المبلغ مطلوب")

    addition = ShiftCashAddition(
        shift_id=shift.id,
        admin_id=current_user.id,
        amount=payload.amount,
        reason=reason,
    )
    db.add(addition)
    await db.commit()
    await db.refresh(addition)

    additions_total = await db.scalar(select(func.sum(ShiftCashAddition.amount)).where(
        ShiftCashAddition.shift_id == shift.id,
    )) or Decimal(0)
    adjusted_closing_cash = (shift.actual_closing_cash or Decimal(0)) + additions_total
    return {
        "id": addition.id,
        "shift_id": shift.id,
        "amount": float(addition.amount),
        "reason": addition.reason,
        "admin_id": addition.admin_id,
        "created_at": addition.created_at.isoformat(),
        "cash_additions_total": float(additions_total),
        "adjusted_closing_cash": float(adjusted_closing_cash),
    }
