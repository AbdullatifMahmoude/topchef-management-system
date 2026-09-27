import asyncio
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import get_db
from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.redis import get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.shifts.service import ShiftsService, get_business_date
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

class AdminExpenseCreate(ExpenseCreate):
    target_date: date
    shift_id: int = Field(gt=0)

class AdminExpenseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    amount: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)
    target_date: date | None = None
    shift_id: int | None = Field(default=None, gt=0)

class CashAdditionCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=2, max_length=500)

async def _current_shift(db: AsyncSession, user_id: int, redis):
    # Roll over sessions left logged in past the 07:00 business-day boundary.
    await ShiftsService(db, redis).start_shift(user_id, sync_web_orders=True)
    from app.modules.shifts.models import CashierShift
    result = await db.execute(select(CashierShift).where(
        CashierShift.user_id == user_id,
        CashierShift.target_date == get_business_date(),
        CashierShift.end_time.is_(None),
    ).order_by(desc(CashierShift.id)))
    return result.scalars().first()

async def _expense_totals(db: AsyncSession, shift_id: int, target_date: date) -> tuple[Decimal, Decimal]:
    from app.modules.shifts.models import ShiftExpense
    shift_total = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.shift_id == shift_id,
        ShiftExpense.is_deleted == False,
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
    from app.modules.shifts.models import ShiftExpense
    expenses = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.shift_id == shift.id,
        ShiftExpense.is_deleted == False,
    )) or Decimal(0)
    return {
        "active": True,
        "shift_id": shift.id,
        "opening_cash": float(shift.opening_cash or 0),
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
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shift, field, value)
    await db.commit()
    return {"message": "Shift cash updated", "shift_id": shift.id}

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
    ).order_by(desc(ShiftExpense.id)))).scalars().all()
    return {
        "shift_id": shift.id,
        "total": float(sum((row.amount or 0) for row in rows)),
        "items": [{"id": row.id, "title": row.title, "amount": float(row.amount), "note": row.note, "created_at": row.created_at.isoformat(), "can_delete": row.user_id == current_user.id} for row in rows],
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
    from app.modules.shifts.models import ShiftExpense
    expense = ShiftExpense(shift_id=shift.id, user_id=current_user.id, target_date=shift.target_date, title=payload.title.strip(), amount=payload.amount, note=payload.note.strip() if payload.note else None)
    db.add(expense)
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
    expense.is_deleted = True
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
    )
    db.add(expense)
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
    changes = payload.model_dump(exclude_unset=True)
    if "target_date" in changes and changes["target_date"] is None:
        raise ValidationError("يوم المصروف مطلوب")
    recorder = await db.get(User, expense.user_id)
    if expense.shift_id is not None and "target_date" in changes and changes["target_date"] != expense.target_date and "shift_id" not in changes:
        raise ValidationError("لا يمكن تغيير يوم مصروف مرتبط بشيفت كاشير")
    owner = None
    if "shift_id" in changes:
        if not recorder or recorder.role != UserRole.ADMIN or changes["shift_id"] is None:
            raise ValidationError("لا يمكن تغيير شيفت مصروف الكاشير")
        _, owner = await _validated_expense_shift(
            db, changes["shift_id"], changes.get("target_date") or expense.target_date,
        )
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if len(changes["title"]) < 2:
            raise ValidationError("اسم بند المصروف مطلوب")
    for field, value in changes.items():
        if field == "note" and value is not None:
            value = value.strip() or None
        setattr(expense, field, value)
    await db.commit()
    await db.refresh(expense)
    if expense.shift_id is not None and owner is None:
        shift = await db.get(CashierShift, expense.shift_id)
        owner = await db.get(User, shift.user_id) if shift else None
    from app.core.events import order_events_manager
    asyncio.create_task(order_events_manager.emit({"type": "EXPENSE_UPDATED", "data": {"shift_id": expense.shift_id, "target_date": expense.target_date.isoformat()}}))
    return _admin_expense_payload(expense, recorder, owner)

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
    expense.is_deleted = True
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
