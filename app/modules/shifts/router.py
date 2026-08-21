import asyncio
from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List, Optional
from datetime import date

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User
from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.modules.shifts.service import ShiftsService, get_business_date

router = APIRouter(prefix="/shifts", tags=["shifts"])

class ShiftCashUpdate(BaseModel):
    opening_cash: Optional[Decimal] = Field(default=None, ge=0)
    actual_closing_cash: Optional[Decimal] = Field(default=None, ge=0)
    closing_note: Optional[str] = Field(default=None, max_length=500)

class ExpenseCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    amount: Decimal = Field(gt=0)
    note: Optional[str] = Field(default=None, max_length=500)

async def _current_shift(db: AsyncSession, user_id: int):
    from app.modules.shifts.models import CashierShift
    result = await db.execute(select(CashierShift).where(
        CashierShift.user_id == user_id,
        CashierShift.end_time.is_(None),
    ).order_by(desc(CashierShift.id)))
    return result.scalars().first()

async def _expense_totals(db: AsyncSession, shift_id: int, target_date: date) -> tuple[Decimal, Decimal]:
    from app.modules.shifts.models import ShiftExpense
    shift_total = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.shift_id == shift_id,
        ShiftExpense.is_deleted == False,
    )) or Decimal("0")
    day_total = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.target_date == target_date,
        ShiftExpense.is_deleted == False,
    )) or Decimal("0")
    return shift_total, day_total

@router.get("/current/cash")
async def get_current_shift_cash(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can view the current shift")
    shift = await _current_shift(db, current_user.id)
    if not shift:
        return {"active": False}
    from app.modules.shifts.models import ShiftExpense
    expenses = await db.scalar(select(func.sum(ShiftExpense.amount)).where(
        ShiftExpense.shift_id == shift.id,
        ShiftExpense.is_deleted == False,
    )) or Decimal("0")
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
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can reconcile the current shift")
    shift = await _current_shift(db, current_user.id)
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
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can view shift expenses")
    shift = await _current_shift(db, current_user.id)
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
        "items": [{"id": row.id, "title": row.title, "amount": float(row.amount), "note": row.note, "created_at": row.created_at.isoformat()} for row in rows],
    }

@router.post("/current/expenses")
async def create_current_expense(
    payload: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can add shift expenses")
    shift = await _current_shift(db, current_user.id)
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
        "shift_total": float(shift_total),
        "day_total": float(day_total),
    }

@router.delete("/current/expenses/{expense_id}")
async def delete_current_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can delete shift expenses")
    from app.modules.shifts.models import ShiftExpense
    shift = await _current_shift(db, current_user.id)
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
    target_date: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("Only admin can view shifts report")
        
    shifts_service = ShiftsService(db)
    dt = target_date or get_business_date()
    return await shifts_service.get_shifts_report(dt)
