import calendar
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from datetime import date, timedelta, datetime, timezone
from app.modules.orders.models import Order
from app.core.enums import OrderStatus
from decimal import Decimal
from typing import List
from . import schemas


# ─────────────────────────────────────────────────────────
# يوم العمل بيبدأ 5 الصبح (نفس المنطق المستخدم في orders)
# ─────────────────────────────────────────────────────────
BUSINESS_DAY_START_HOUR = 5
EGYPT_TZ = timezone(timedelta(hours=3))


def get_business_date() -> date:
    """يحسب يوم العمل الحالي (الشيفت بيبدأ 5 صباحاً)"""
    now = datetime.now(EGYPT_TZ)
    if now.hour < BUSINESS_DAY_START_HOUR:
        return (now - timedelta(days=1)).date()
    return now.date()


# ─────────────────────────────────────────────────────────
# الإحصائيات الإجمالية (query سريع بدون تحميل العلاقات)
# ─────────────────────────────────────────────────────────
async def get_report_summary(db: AsyncSession, start_date: date, end_date: date) -> schemas.ReportSummary:
    stmt = select(
        func.count(Order.id).label('total_orders'),
        func.sum(case((Order.order_status == OrderStatus.CANCELLED, 1), else_=0)).label('cancelled_orders'),
        func.sum(case((Order.order_status != OrderStatus.CANCELLED, 1), else_=0)).label('successful_orders'),
        # Delivery is collected on behalf of the delivery operation; it is not
        # restaurant sales and must not inflate report revenue or averages.
        func.sum(
            case(
                (Order.order_status != OrderStatus.CANCELLED, Order.total_amount - Order.delivery_fee),
                else_=0,
            )
        ).label('total_revenue'),
        func.sum(case((Order.order_status != OrderStatus.CANCELLED, Order.subtotal), else_=0)).label('total_subtotal'),
        func.sum(case((Order.order_status != OrderStatus.CANCELLED, Order.discount_amount), else_=0)).label('total_discount'),
        func.sum(case((Order.order_status != OrderStatus.CANCELLED, Order.delivery_fee), else_=0)).label('total_delivery_fee'),
    ).filter(
        Order.order_date >= start_date,
        Order.order_date <= end_date
    )

    result = await db.execute(stmt)
    row = result.first()

    successful_orders = row.successful_orders or 0
    total_revenue = row.total_revenue or Decimal('0.00')
    average_order_value = (total_revenue / successful_orders) if successful_orders > 0 else Decimal('0.00')

    return schemas.ReportSummary(
        total_orders=row.total_orders or 0,
        successful_orders=successful_orders,
        cancelled_orders=row.cancelled_orders or 0,
        total_revenue=total_revenue,
        average_order_value=average_order_value,
        total_subtotal=row.total_subtotal or Decimal('0.00'),
        total_discount=row.total_discount or Decimal('0.00'),
        total_delivery_fee=row.total_delivery_fee or Decimal('0.00'),
    )


# ─────────────────────────────────────────────────────────
# قائمة الطلبات (بـ limit وبدون تحميل items عشان السرعة)
# ─────────────────────────────────────────────────────────
async def get_report_orders(db: AsyncSession, start_date: date, end_date: date) -> List[schemas.OrderReportItem]:
    stmt = (
        select(
            Order.order_number,
            Order.order_type,
            (Order.total_amount - Order.delivery_fee).label("total_amount"),
            Order.created_at,
            Order.order_status,
        )
        .filter(
            Order.order_date >= start_date,
            Order.order_date <= end_date,
        )
        .order_by(Order.created_at.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    report_orders = []
    for row in rows:
        otype = str(row.order_type.name if hasattr(row.order_type, 'name') else row.order_type)
        if "DINE_IN" in otype:
            otype = "صالة"
        elif "TAKEAWAY" in otype:
            otype = "تيك اوي"
        elif "DELIVERY" in otype:
            otype = "دليفري"

        status = str(row.order_status.name if hasattr(row.order_status, 'name') else row.order_status)
        if "CANCELLED" in status:
            otype += " (ملغي)"

        report_orders.append(schemas.OrderReportItem(
            order_number=row.order_number,
            order_type=otype,
            items_summary="",
            total_amount=row.total_amount,
            created_at_time=row.created_at.strftime("%I:%M %p") if row.created_at else "",
        ))
    return report_orders


# ─────────────────────────────────────────────────────────
# التقارير
# ─────────────────────────────────────────────────────────
async def get_daily_report(db: AsyncSession, target_date: date) -> schemas.DailyReportResponse:
    # التقرير اليومي بيستخدم يوم العمل (الشيفت من 5 صباحاً)
    business_date = target_date or get_business_date()
    summary = await get_report_summary(db, business_date, business_date)
    orders = await get_report_orders(db, business_date, business_date)
    return schemas.DailyReportResponse(report_date=business_date, summary=summary, orders=orders)


async def get_weekly_report(db: AsyncSession, target_date: date) -> schemas.WeeklyReportResponse:
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    summary = await get_report_summary(db, start_of_week, end_of_week)
    orders = await get_report_orders(db, start_of_week, end_of_week)
    return schemas.WeeklyReportResponse(start_date=start_of_week, end_date=end_of_week, summary=summary, orders=orders)


async def get_monthly_report(db: AsyncSession, year: int, month: int) -> schemas.MonthlyReportResponse:
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)
    summary = await get_report_summary(db, start_date, end_date)
    orders = await get_report_orders(db, start_date, end_date)
    return schemas.MonthlyReportResponse(year=year, month=month, summary=summary, orders=orders)


async def get_yearly_report(db: AsyncSession, year: int) -> schemas.YearlyReportResponse:
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    summary = await get_report_summary(db, start_date, end_date)
    orders = await get_report_orders(db, start_date, end_date)
    return schemas.YearlyReportResponse(year=year, summary=summary, orders=orders)

async def get_custom_report(db: AsyncSession, start_date: date, end_date: date) -> schemas.CustomReportResponse:
    summary = await get_report_summary(db, start_date, end_date)
    orders = await get_report_orders(db, start_date, end_date)
    return schemas.CustomReportResponse(start_date=start_date, end_date=end_date, summary=summary, orders=orders)
