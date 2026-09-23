from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.business_calendar import business_day_start, get_current_business_date
from app.core.enums import OrderStatus, OrderType, PaymentMethod
from app.core.logging import logger
from app.modules.orders.models import Order
from app.modules.shifts.models import CashierShift, ShiftCashAddition, ShiftExpense


def restaurant_sales_amount(order):
    """Restaurant revenue keeps hall service, but excludes rider-owned delivery fees."""
    total = order.total_amount or 0
    if order.order_type == OrderType.DELIVERY:
        return total - (order.delivery_fee or 0)
    return total

def get_business_date() -> date:
    return get_current_business_date()

class ShiftsService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis

    async def _open_web_orders_for_first_shift(self, was_active: bool, sync_web_orders: bool) -> None:
        if sync_web_orders and not was_active:
            from app.modules.settings.service import SettingsService
            await SettingsService(self.db, self.redis).toggle_web_orders(True)
            await self.db.commit()

    async def _username_for(self, user_id: int) -> str | None:
        from app.modules.users.models import User
        user = await self.db.get(User, user_id)
        return user.username if user else None

    async def start_shift(self, user_id: int, sync_web_orders: bool = False):
        target_date = get_business_date()
        was_active = True
        if sync_web_orders:
            active_count = await self.db.scalar(select(func.count(CashierShift.id)).where(
                CashierShift.target_date == target_date, CashierShift.end_time.is_(None))) or 0
            was_active = active_count > 0
        # Detect sessions left logged in across the 07:00 business-day cutoff.
        active_shift = await self.db.scalar(
            select(CashierShift).where(
                CashierShift.user_id == user_id,
                CashierShift.end_time.is_(None),
            ).order_by(desc(CashierShift.id))
        )
        if active_shift and active_shift.target_date == target_date:
            await self._open_web_orders_for_first_shift(was_active, sync_web_orders)
            return active_shift
        if active_shift:
            # End stale shifts so their expenses cannot appear in the new day.
            active_shift.end_time = datetime.now(UTC).replace(tzinfo=None)
            await self.db.flush()

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

            await self._open_web_orders_for_first_shift(was_active, sync_web_orders)
            return last_shift

        else:
            # Create a new shift since the last one belongs to someone else, or no shifts exist today
            new_shift = CashierShift(
                user_id=user_id,
                target_date=target_date,
                start_time=datetime.now(UTC).replace(tzinfo=None)
            )
            self.db.add(new_shift)
            await self.db.flush() # To get the ID
            
            await self.db.commit()
            await self._open_web_orders_for_first_shift(was_active, sync_web_orders)
            return new_shift
            

    async def end_shift(self, user_id: int, sync_web_orders: bool = False):
        # Do not restrict this lookup by target_date: a night shift can start on
        # one business date and be closed after the 07:00 cutoff on the next.
        query = select(CashierShift).where(
            CashierShift.user_id == user_id,
            CashierShift.end_time.is_(None)
        ).order_by(desc(CashierShift.id))
        result = await self.db.execute(query)
        active_shift = result.scalars().first()
        
        if active_shift:
            active_shift.end_time = datetime.now(UTC).replace(tzinfo=None)
            await self.db.commit()
            if sync_web_orders:
                remaining = await self.db.scalar(select(func.count(CashierShift.id)).where(
                    CashierShift.end_time.is_(None))) or 0
                if not remaining:
                    from app.modules.settings.service import SettingsService
                    await SettingsService(self.db, self.redis).toggle_web_orders(False)
                    await self.db.commit()
            
        else:
            logger.warning(
                "end_shift: no active shift found for user_id=%s on %s",
                user_id,
                get_business_date(),
            )

    async def get_shifts_report(self, target_date: date) -> list[dict[str, Any]]:
        # Fetch shifts for the day
        query = select(CashierShift).options(selectinload(CashierShift.user)).where(
            CashierShift.target_date == target_date
        )
        result = await self.db.execute(query)
        shifts = result.scalars().all()
        # Fetch orders for the day to compute stats
        # We define business day boundaries in LOCAL naive time because Order.created_at is stored in LOCAL naive time.
        # From 7 AM target_date to 6:59:59 AM next day
        start_local = business_day_start(target_date)
        end_local = start_local + timedelta(days=1)

        def shift_time_to_local(dt):
            if not dt:
                return None
            if dt.tzinfo is not None:
                return dt.astimezone(timezone(timedelta(hours=3))).replace(tzinfo=None)
            # CashierShift timestamps are written with datetime.utcnow().
            return dt + timedelta(hours=3)

        now_local = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
        # The normal report window ends at 07:00, but an actual shift is the
        # source of truth when it continues beyond that cutoff.
        report_end_local = max(
            [end_local, *(
                shift_time_to_local(shift.end_time) or now_local
                for shift in shifts
            )]
        )

        orders_query = select(
            Order.created_by_user_id,
            Order.created_at,
            Order.order_status,
            Order.total_amount,
            Order.delivery_fee,
            Order.discount_amount,
            Order.payment_method,
            Order.order_type,
        ).where(
            Order.created_at >= start_local,
            Order.created_at < report_end_local,
            Order.is_deleted == False,
        )

        orders_result = await self.db.execute(orders_query)
        day_orders = orders_result.all()
        expenses_result = await self.db.execute(select(ShiftExpense).where(
            ShiftExpense.target_date == target_date,
            ShiftExpense.is_deleted == False,
        ))
        day_expenses = expenses_result.scalars().all()
        additions_result = await self.db.execute(
            select(ShiftCashAddition).options(selectinload(ShiftCashAddition.admin)).where(
                ShiftCashAddition.shift_id.in_([shift.id for shift in shifts])
            )
        ) if shifts else None
        day_additions = additions_result.scalars().all() if additions_result else []

        def format_dt(dt):
            if not dt:
                return None
            s = dt.isoformat()
            s = s.removesuffix("+00:00")
            if not s.endswith("Z"):
                s += "Z"
            return s

        report = []
        for shift in shifts:
            shift_start_local = shift_time_to_local(shift.start_time) or start_local
            shift_end_local = shift_time_to_local(shift.end_time) or now_local
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
            shift_additions = [addition for addition in day_additions if addition.shift_id == shift.id]
            cash_additions_total = sum((addition.amount or 0) for addition in shift_additions)
            adjusted_closing_cash = (
                shift.actual_closing_cash + cash_additions_total
                if shift.actual_closing_cash is not None else None
            )
            cash_difference = (
                (adjusted_closing_cash - expected_cash)
                if adjusted_closing_cash is not None else None
            )
            duration_end = shift_time_to_local(shift.end_time) or now_local
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
                "cash_additions_total": float(cash_additions_total),
                "adjusted_closing_cash": float(adjusted_closing_cash) if adjusted_closing_cash is not None else None,
                "cash_additions": [{
                    "id": addition.id,
                    "amount": float(addition.amount),
                    "reason": addition.reason,
                    "admin_id": addition.admin_id,
                    "admin_name": addition.admin.full_name or addition.admin.username if addition.admin else "—",
                    "created_at": format_dt(addition.created_at),
                } for addition in shift_additions],
                "cash_difference": float(cash_difference) if cash_difference is not None else None,
                "closing_note": shift.closing_note,
                "duration_minutes": duration_minutes,
                "status": "active" if shift.end_time is None else "closed",
                "target_date": shift.target_date.isoformat()
            })
            
        return report
