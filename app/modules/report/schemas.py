from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from decimal import Decimal

class ReportSummary(BaseModel):
    total_orders: int
    successful_orders: int
    cancelled_orders: int
    total_revenue: Decimal
    average_order_value: Decimal
    total_subtotal: Decimal
    total_discount: Decimal
    total_delivery_fee: Decimal

class OrderReportItem(BaseModel):
    order_number: str
    order_type: str
    items_summary: str
    total_amount: Decimal
    order_date: Optional[date] = None
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

class ReportDataMixin(BaseModel):
    summary: ReportSummary
    orders: List[OrderReportItem] = Field(default_factory=list)
    orders_offset: int = 0
    orders_limit: int = 50
    top_items: List[TopSellingItem] = Field(default_factory=list)
    revenue_trend: List[RevenueTrendPoint] = Field(default_factory=list)
    activity_breakdown: List[ActivityBreakdownPoint] = Field(default_factory=list)

class ReportOrdersPage(BaseModel):
    orders: List[OrderReportItem] = Field(default_factory=list)
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
