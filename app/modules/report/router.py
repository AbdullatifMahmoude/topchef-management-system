from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from typing import Optional
from app.core.database import get_db
from . import schemas, service
from app.modules.auth.dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.get("/orders", response_model=schemas.ReportOrdersPage)
async def get_report_orders_page(
    start_date: date = Query(...),
    end_date: date = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    orders = await service.get_report_orders(db, start_date, end_date, limit=limit, offset=offset)
    return schemas.ReportOrdersPage(orders=orders, offset=offset, limit=limit)

@router.get("/daily", response_model=schemas.DailyReportResponse)
async def get_daily_report(
    target_date: Optional[date] = Query(default=None, description="Date for the report (YYYY-MM-DD). Defaults to current business day (5 AM shift)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # لو ماحددش تاريخ، نستخدم يوم العمل الحالي (الشيفت من 5 صباحاً)
    actual_date = target_date or service.get_business_date()
    return await service.get_daily_report(db, actual_date, limit, offset)

@router.get("/weekly", response_model=schemas.WeeklyReportResponse)
async def get_weekly_report(
    target_date: date = Query(default_factory=date.today, description="Any date within the target week (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return await service.get_weekly_report(db, target_date, limit, offset)

@router.get("/monthly", response_model=schemas.MonthlyReportResponse)
async def get_monthly_report(
    year: int = Query(..., description="Year of the report"),
    month: int = Query(..., description="Month of the report (1-12)", ge=1, le=12),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return await service.get_monthly_report(db, year, month, limit, offset)

@router.get("/yearly", response_model=schemas.YearlyReportResponse)
async def get_yearly_report(
    year: int = Query(..., description="Year of the report"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return await service.get_yearly_report(db, year, limit, offset)

@router.get("/custom", response_model=schemas.CustomReportResponse)
async def get_custom_report(
    start_date: date = Query(..., description="Start date for the custom report (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date for the custom report (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return await service.get_custom_report(db, start_date, end_date, limit, offset)
