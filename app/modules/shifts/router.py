from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List, Optional
from datetime import date

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User
from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError
from app.modules.shifts.service import ShiftsService, get_business_date

router = APIRouter(prefix="/shifts", tags=["shifts"])

class ShiftCashUpdate(BaseModel):
    opening_cash: Optional[Decimal] = Field(default=None, ge=0)
    cash_expenses: Optional[Decimal] = Field(default=None, ge=0)
    actual_closing_cash: Optional[Decimal] = Field(default=None, ge=0)
    closing_note: Optional[str] = Field(default=None, max_length=500)

@router.patch("/current/cash")
async def update_current_shift_cash(
    payload: ShiftCashUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.CASHIER:
        raise AuthorizationError("Only cashier can reconcile the current shift")
    from app.modules.shifts.models import CashierShift
    result = await db.execute(select(CashierShift).where(
        CashierShift.user_id == current_user.id,
        CashierShift.end_time.is_(None),
    ).order_by(desc(CashierShift.id)))
    shift = result.scalars().first()
    if not shift:
        return {"message": "No active shift"}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shift, field, value)
    await db.commit()
    return {"message": "Shift cash updated", "shift_id": shift.id}

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
