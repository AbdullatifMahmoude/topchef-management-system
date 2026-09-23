from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ReportSummary(BaseModel):
    total_orders: int
    successful_orders: int
    cancelled_orders: int
    total_revenue: Decimal
    average_order_value: Decimal
    total_subtotal: Decimal
    total_discount: Decimal
    total_delivery_fee: Decimal
    total_expenses: Decimal
    net_profit: Decimal

class OrderReportItem(BaseModel):
    order_number: str
    order_type: str
    items_summary: str
    total_amount: Decimal
    order_date: date | None = None
    created_at_time: str
    status: str = "completed"

class TopSellingItem(BaseModel):
    name: str
    quantity: int
    revenue: Decimal

class RevenueTrendPoint(BaseModel):
    period_date: date
    revenue: Decimal

class ActivityBreakdownPoint(BaseModel):
    order_type: str
    hour: int
    count: int

class ExpenseReportItem(BaseModel):
    id: int
    title: str
    amount: Decimal
    note: str | None = None
    cashier_name: str
    target_date: date
    created_at: datetime

class ReportDataMixin(BaseModel):
    summary: ReportSummary
    orders: list[OrderReportItem] = Field(default_factory=list)
    orders_offset: int = 0
    orders_limit: int = 50
    top_items: list[TopSellingItem] = Field(default_factory=list)
    revenue_trend: list[RevenueTrendPoint] = Field(default_factory=list)
    activity_breakdown: list[ActivityBreakdownPoint] = Field(default_factory=list)
    expenses: list[ExpenseReportItem] = Field(default_factory=list)

class ReportOrdersPage(BaseModel):
    orders: list[OrderReportItem] = Field(default_factory=list)
    offset: int
    limit: int

class DailyReportResponse(ReportDataMixin):
    report_date: date

class WeeklyReportResponse(ReportDataMixin):
    start_date: date
    end_date: date

class MonthlyReportResponse(ReportDataMixin):
    year: int
    month: int

class YearlyReportResponse(ReportDataMixin):
    year: int

class CustomReportResponse(ReportDataMixin):
    start_date: date
    end_date: date
