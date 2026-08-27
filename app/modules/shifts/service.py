from datetime import datetime, date, timedelta, timezone
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List, Dict, Any, Optional

from app.modules.shifts.models import CashierShift, ShiftExpense
from app.modules.orders.models import Order
from app.core.enums import OrderStatus, PaymentMethod, OrderType
from app.core.logging import logger


def restaurant_sales_amount(order):
    """Restaurant revenue keeps hall service, but excludes rider-owned delivery fees."""
    total = order.total_amount or 0
    if order.order_type == OrderType.DELIVERY:
        return total - (order.delivery_fee or 0)
    return total

def get_business_date() -> date:
    # Business shift starts at 5am (UTC+3)
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz)
    if now.hour < 5:
        return (now - timedelta(days=1)).date()
    return now.date()

class ShiftsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _username_for(self, user_id: int) -> Optional[str]:
        from app.modules.users.models import User
        user = await self.db.get(User, user_id)
        return user.username if user else None

    async def start_shift(self, user_id: int):
        target_date = get_business_date()
        # Get the absolute last shift for today, regardless of who owns it
        last_shift_query = select(CashierShift).where(
            CashierShift.target_date == target_date
        ).order_by(desc(CashierShift.id))
        result = await self.db.execute(last_shift_query)
        last_shift = result.scalars().first()
        
        if last_shift and last_shift.user_id == user_id:
            if last_shift.end_time is not None:
                # Reopen the shift since no one else logged in between
                last_shift.end_time = None
                await self.db.commit()

            else:
                # The shift is already open.
                await self.db.commit()

        else:
            # Create a new shift since the last one belongs to someone else, or no shifts exist today
            new_shift = CashierShift(
                user_id=user_id,
                target_date=target_date,
                start_time=datetime.utcnow()
            )
            self.db.add(new_shift)
            await self.db.flush() # To get the ID
            
            await self.db.commit()
            

    async def end_shift(self, user_id: int):
        target_date = get_business_date()
        query = select(CashierShift).where(
            CashierShift.user_id == user_id,
            CashierShift.target_date == target_date,
            CashierShift.end_time.is_(None)
        )
        result = await self.db.execute(query)
        active_shift = result.scalars().first()
        
        if active_shift:
            active_shift.end_time = datetime.utcnow()
            await self.db.commit()
            
        else:
            logger.warning(
                "end_shift: no active shift found for user_id=%s on %s",
                user_id,
                target_date,
            )

    async def get_shifts_report(self, target_date: date) -> List[Dict[str, Any]]:
        # Fetch shifts for the day
        query = select(CashierShift).options(selectinload(CashierShift.user)).where(
            CashierShift.target_date == target_date
        )
        result = await self.db.execute(query)
        shifts = result.scalars().all()
        # Fetch orders for the day to compute stats
        # We define business day boundaries in LOCAL naive time because Order.created_at is stored in LOCAL naive time.
        # From 5 AM target_date to 4:59:59 AM next day
        start_local = datetime.combine(target_date, datetime.min.time()).replace(hour=5)
        end_local = start_local + timedelta(days=1)

        orders_query = select(
            Order.created_by_user_id,
            Order.created_at,
            Order.order_status,
            Order.total_amount,
            Order.delivery_fee,
            Order.discount_amount,
            Order.payment_method,
        ).where(
            Order.created_at >= start_local,
            Order.created_at < end_local,
            Order.is_deleted == False,
        )

        orders_result = await self.db.execute(orders_query)
        day_orders = orders_result.all()
        expenses_result = await self.db.execute(select(ShiftExpense).where(
            ShiftExpense.target_date == target_date,
            ShiftExpense.is_deleted == False,
        ))
        day_expenses = expenses_result.scalars().all()

        def shift_time_to_local(dt):
            if not dt:
                return None
            if dt.tzinfo is not None:
                return dt.astimezone(timezone(timedelta(hours=3))).replace(tzinfo=None)
            # CashierShift timestamps are written with datetime.utcnow().
            return dt + timedelta(hours=3)

        def format_dt(dt):
            if not dt:
                return None
            s = dt.isoformat()
            if s.endswith("+00:00"):
                s = s[:-6]
            if not s.endswith("Z"):
                s += "Z"
            return s

        report = []
        for shift in shifts:
            shift_start_local = shift_time_to_local(shift.start_time) or start_local
            shift_end_local = shift_time_to_local(shift.end_time) if shift.end_time else end_local
            shift_orders = [
                order for order in day_orders
                if order.created_by_user_id == shift.user_id
                and shift_start_local <= order.created_at < shift_end_local
            ]
            successful = [order for order in shift_orders if order.order_status != OrderStatus.CANCELLED]
            cancelled_count = len(shift_orders) - len(successful)
            total_sales = sum(restaurant_sales_amount(order) for order in successful)
            total_discount = sum((order.discount_amount or 0) for order in successful)
            total_delivery_fee = sum(
                (order.delivery_fee or 0) for order in successful
                if order.order_type == OrderType.DELIVERY
            )
            payment_sales = {
                method.value: sum(
                    restaurant_sales_amount(order)
                    for order in successful
                    if order.payment_method == method
                )
                for method in PaymentMethod
            }
            opening_cash = shift.opening_cash or 0
            cash_expenses = sum((expense.amount or 0) for expense in day_expenses if expense.shift_id == shift.id)
            expected_cash = opening_cash + payment_sales[PaymentMethod.CASH.value] - cash_expenses
            cash_difference = (
                (shift.actual_closing_cash - expected_cash)
                if shift.actual_closing_cash is not None else None
            )
            duration_end = shift_time_to_local(shift.end_time) or datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
            duration_minutes = max(0, int((duration_end - shift_start_local).total_seconds() // 60))
            report.append({
                "id": shift.id,
                "user_id": shift.user_id,
                "cashier_name": shift.user.full_name or shift.user.username,
                "start_time": format_dt(shift.start_time),
                "end_time": format_dt(shift.end_time),
                "total_orders": len(shift_orders),
                "successful_orders": len(successful),
                "cancelled_orders": cancelled_count,
                "total_sales": float(total_sales),
                "average_order": float(total_sales / len(successful)) if successful else 0.0,
                "total_discount": float(total_discount),
                "total_delivery_fee": float(total_delivery_fee),
                "cash_sales": float(payment_sales[PaymentMethod.CASH.value]),
                "instapay_sales": float(payment_sales[PaymentMethod.INSTAPAY.value]),
                "wallet_sales": float(payment_sales[PaymentMethod.WALLET.value]),
                "opening_cash": float(opening_cash),
                "cash_expenses": float(cash_expenses),
                "expected_cash": float(expected_cash),
                "actual_closing_cash": float(shift.actual_closing_cash) if shift.actual_closing_cash is not None else None,
                "cash_difference": float(cash_difference) if cash_difference is not None else None,
                "closing_note": shift.closing_note,
                "duration_minutes": duration_minutes,
                "status": "active" if shift.end_time is None else "closed",
                "target_date": shift.target_date.isoformat()
            })
            
        return report
