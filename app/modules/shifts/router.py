from fastapi import APIRouter, Depends, Query
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
