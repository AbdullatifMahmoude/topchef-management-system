from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError
from app.modules.auth.dependencies import get_current_user

from . import schemas, service

router = APIRouter(prefix="/reports", tags=["Reports"])

def require_admin_shift_filter(current_user, shift_id: int | None) -> None:
    if shift_id is not None and current_user.role != UserRole.ADMIN:
        raise AuthorizationError("فلتر الشيفت متاح للأدمن فقط")

@router.get("/shifts")
async def get_report_shifts(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise AuthorizationError("شيفتات التقارير متاحة للأدمن فقط")
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return await service.list_report_shifts(db, start_date, end_date)

@router.get("/orders", response_model=schemas.ReportOrdersPage)
async def get_report_orders_page(
    start_date: date = Query(...),
    end_date: date = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    shift_id: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    require_admin_shift_filter(current_user, shift_id)
    shift = await service.get_shift_for_report(db, shift_id, start_date, end_date)
    orders = await service.get_report_orders(db, start_date, end_date, limit=limit, offset=offset, shift=shift)
    return schemas.ReportOrdersPage(orders=orders, offset=offset, limit=limit)

@router.get("/daily", response_model=schemas.DailyReportResponse)
async def get_daily_report(
    target_date: date | None = Query(default=None, description="Date for the report (YYYY-MM-DD). Defaults to current business day (7 AM shift)"),
    shift_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # لو ماحددش تاريخ، نستخدم يوم العمل الحالي (الشيفت من 7 صباحاً)
    actual_date = target_date or service.get_business_date()
    require_admin_shift_filter(current_user, shift_id)
    return await service.get_daily_report(db, actual_date, limit, offset, shift_id)

@router.get("/weekly", response_model=schemas.WeeklyReportResponse)
async def get_weekly_report(
    target_date: date | None = Query(default=None, description="Any date within the target week (YYYY-MM-DD)"),
    shift_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    require_admin_shift_filter(current_user, shift_id)
    return await service.get_weekly_report(db, target_date or service.get_business_date(), limit, offset, shift_id)

@router.get("/monthly", response_model=schemas.MonthlyReportResponse)
async def get_monthly_report(
    year: int = Query(..., description="Year of the report"),
    month: int = Query(..., description="Month of the report (1-12)", ge=1, le=12),
    shift_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    require_admin_shift_filter(current_user, shift_id)
    return await service.get_monthly_report(db, year, month, limit, offset, shift_id)

@router.get("/yearly", response_model=schemas.YearlyReportResponse)
async def get_yearly_report(
    year: int = Query(..., description="Year of the report"),
    shift_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    require_admin_shift_filter(current_user, shift_id)
    return await service.get_yearly_report(db, year, limit, offset, shift_id)

@router.get("/custom", response_model=schemas.CustomReportResponse)
async def get_custom_report(
    start_date: date = Query(..., description="Start date for the custom report (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date for the custom report (YYYY-MM-DD)"),
    shift_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    require_admin_shift_filter(current_user, shift_id)
    return await service.get_custom_report(db, start_date, end_date, limit, offset, shift_id)
