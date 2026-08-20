import calendar
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, cast, Integer
from datetime import date, timedelta, datetime, timezone
from app.modules.orders.models import Order, OrderItem
from app.modules.menu.models import Product
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
def normalize_order_type(value) -> str:
    otype = str(value.name if hasattr(value, "name") else value).upper()
    if "DINE_IN" in otype or "HALL" in otype:
        return "صالة"
    if "TAKEAWAY" in otype or "TAKE_AWAY" in otype:
        return "تيك اوي"
    if "DELIVERY" in otype:
        return "دليفري"
    if "ONLINE" in otype:
        return "أون لاين"
    return str(value)


async def get_report_orders(
    db: AsyncSession, start_date: date, end_date: date, limit: int = 50, offset: int = 0
) -> List[schemas.OrderReportItem]:
    stmt = (
        select(
            Order.order_number,
            Order.order_type,
            (Order.total_amount - Order.delivery_fee).label("total_amount"),
            Order.order_date,
            Order.created_at,
            Order.order_status,
        )
        .filter(
            Order.order_date >= start_date,
            Order.order_date <= end_date,
        )
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    report_orders = []
    for row in rows:
        otype = normalize_order_type(row.order_type)

        status = str(row.order_status.name if hasattr(row.order_status, 'name') else row.order_status)
        if "CANCELLED" in status:
            otype += " (ملغي)"

        report_orders.append(schemas.OrderReportItem(
            order_number=row.order_number,
            order_type=otype,
            items_summary="",
            total_amount=row.total_amount,
            order_date=row.order_date,
            created_at_time=row.created_at.strftime("%I:%M %p") if row.created_at else "",
            status="cancelled" if "CANCELLED" in status else "completed",
        ))
    return report_orders


async def get_top_selling_items(db: AsyncSession, start_date: date, end_date: date) -> List[schemas.TopSellingItem]:
    stmt = (
        select(
            Product.product_name.label("name"),
            func.sum(OrderItem.quantity).label("quantity"),
            func.sum(OrderItem.total_price).label("revenue"),
        )
        .select_from(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(
            Order.order_date >= start_date,
            Order.order_date <= end_date,
            Order.order_status != OrderStatus.CANCELLED,
            OrderItem.is_deleted == False,
        )
        .group_by(Product.id, Product.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
    )
    rows = (await db.execute(stmt)).all()
    return [schemas.TopSellingItem(name=row.name, quantity=row.quantity or 0, revenue=row.revenue or Decimal("0.00")) for row in rows]


async def get_revenue_trend(db: AsyncSession, start_date: date, end_date: date) -> List[schemas.RevenueTrendPoint]:
    stmt = (
        select(
            Order.order_date.label("period_date"),
            func.sum(Order.total_amount - Order.delivery_fee).label("revenue"),
        )
        .filter(
            Order.order_date >= start_date,
            Order.order_date <= end_date,
            Order.order_status != OrderStatus.CANCELLED,
        )
        .group_by(Order.order_date)
        .order_by(Order.order_date)
    )
    rows = (await db.execute(stmt)).all()
    return [schemas.RevenueTrendPoint(period_date=row.period_date, revenue=row.revenue or Decimal("0.00")) for row in rows]


async def get_activity_breakdown(db: AsyncSession, start_date: date, end_date: date) -> List[schemas.ActivityBreakdownPoint]:
    hour_expr = cast(func.extract("hour", Order.created_at), Integer)
    stmt = (
        select(Order.order_type, hour_expr.label("hour"), func.count(Order.id).label("count"))
        .filter(
            Order.order_date >= start_date,
            Order.order_date <= end_date,
            Order.order_status != OrderStatus.CANCELLED,
        )
        .group_by(Order.order_type, hour_expr)
    )
    rows = (await db.execute(stmt)).all()
    return [
        schemas.ActivityBreakdownPoint(
            order_type=normalize_order_type(row.order_type),
            hour=int(row.hour or 0),
            count=row.count or 0,
        )
        for row in rows
    ]


async def get_report_data(db: AsyncSession, start_date: date, end_date: date, limit: int, offset: int):
    summary = await get_report_summary(db, start_date, end_date)
    orders = await get_report_orders(db, start_date, end_date, limit=limit, offset=offset)
    top_items = await get_top_selling_items(db, start_date, end_date)
    revenue_trend = await get_revenue_trend(db, start_date, end_date)
    activity_breakdown = await get_activity_breakdown(db, start_date, end_date)
    return {
        "summary": summary,
        "orders": orders,
        "orders_offset": offset,
        "orders_limit": limit,
        "top_items": top_items,
        "revenue_trend": revenue_trend,
        "activity_breakdown": activity_breakdown,
    }


# ─────────────────────────────────────────────────────────
# التقارير
# ─────────────────────────────────────────────────────────
async def get_daily_report(db: AsyncSession, target_date: date, limit: int = 50, offset: int = 0) -> schemas.DailyReportResponse:
    # التقرير اليومي بيستخدم يوم العمل (الشيفت من 5 صباحاً)
    business_date = target_date or get_business_date()
    data = await get_report_data(db, business_date, business_date, limit, offset)
    return schemas.DailyReportResponse(report_date=business_date, **data)


async def get_weekly_report(db: AsyncSession, target_date: date, limit: int = 50, offset: int = 0) -> schemas.WeeklyReportResponse:
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    data = await get_report_data(db, start_of_week, end_of_week, limit, offset)
    return schemas.WeeklyReportResponse(start_date=start_of_week, end_date=end_of_week, **data)


async def get_monthly_report(db: AsyncSession, year: int, month: int, limit: int = 50, offset: int = 0) -> schemas.MonthlyReportResponse:
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)
    data = await get_report_data(db, start_date, end_date, limit, offset)
    return schemas.MonthlyReportResponse(year=year, month=month, **data)


async def get_yearly_report(db: AsyncSession, year: int, limit: int = 50, offset: int = 0) -> schemas.YearlyReportResponse:
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    data = await get_report_data(db, start_date, end_date, limit, offset)
    return schemas.YearlyReportResponse(year=year, **data)

async def get_custom_report(db: AsyncSession, start_date: date, end_date: date, limit: int = 50, offset: int = 0) -> schemas.CustomReportResponse:
    data = await get_report_data(db, start_date, end_date, limit, offset)
    return schemas.CustomReportResponse(start_date=start_date, end_date=end_date, **data)
