from pydantic import BaseModel
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
    created_at_time: str

class DailyReportResponse(BaseModel):
    report_date: date
    summary: ReportSummary
    orders: List[OrderReportItem] = []

class WeeklyReportResponse(BaseModel):
    start_date: date
    end_date: date
    summary: ReportSummary
    orders: List[OrderReportItem] = []

class MonthlyReportResponse(BaseModel):
    year: int
    month: int
    summary: ReportSummary
    orders: List[OrderReportItem] = []

class YearlyReportResponse(BaseModel):
    year: int
    summary: ReportSummary
    orders: List[OrderReportItem] = []

class CustomReportResponse(BaseModel):
    start_date: date
    end_date: date
    summary: ReportSummary
    orders: List[OrderReportItem] = []
