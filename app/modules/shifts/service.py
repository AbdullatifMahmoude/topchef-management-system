from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.business_calendar import business_day_start, get_current_business_date
from app.core.enums import OrderSource, OrderStatus, OrderType, PaymentMethod
from app.core.exceptions import ValidationError
from app.core.logging import logger
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.shifts.models import (
    CashierShift,
    OrderCashMovement,
    ShiftCashAddition,
    ShiftCashAdjustment,
    ShiftCloseSnapshot,
    ShiftExpense,
)


def restaurant_sales_amount(order):
    """Restaurant revenue keeps hall service, but excludes rider-owned delivery fees."""
    total = order.total_amount or 0
    if order.order_type == OrderType.DELIVERY:
        return total - (order.delivery_fee or 0)
    return total

def get_business_date() -> date:
    return get_current_business_date()

# The owner approved carrying this one mixed rollout shift across the next
# business-day boundary. Closed historical shifts retain their original mode.
MIXED_CUTOVER_SHIFT_ID = 135
MIXED_CUTOVER_SHIFT_DATE = date(2026, 10, 27)


def is_approved_cutover_shift(shift: CashierShift) -> bool:
    return shift.id == MIXED_CUTOVER_SHIFT_ID and shift.target_date == MIXED_CUTOVER_SHIFT_DATE

class ShiftsService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis

    async def shift_uses_cash_ledger(self, shift: CashierShift) -> bool:
        if getattr(shift, "cash_tracking_enabled", False):
            return True
        # A closed legacy shift keeps its historical calculation. The mixed
        # active shift is persisted as tracked when it closes.
        if getattr(shift, "end_time", None) is not None:
            return False
        if not getattr(shift, "id", None) or not getattr(shift, "start_time", None):
            return False
        if (getattr(shift, "target_date", None) != get_current_business_date()
                and not is_approved_cutover_shift(shift)):
            return False
        from app.modules.shifts.cash_custody import shift_local_time

        end_local = shift_local_time(shift.end_time) if shift.end_time else datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
        tracked_order = await self.db.scalar(select(Order.id).where(
            Order.created_by_user_id == shift.user_id,
            Order.order_source == OrderSource.CASHIER,
            Order.cash_tracking_enabled == True,
            Order.created_at >= shift_local_time(shift.start_time),
            Order.created_at < end_local,
        ).limit(1))
        return tracked_order is not None

    async def _open_web_orders_for_first_shift(self, was_active: bool, sync_web_orders: bool) -> None:
        if sync_web_orders and not was_active:
            from app.modules.settings.service import SettingsService
            await SettingsService(self.db, self.redis).toggle_web_orders(True)
            await self.db.commit()

    async def _username_for(self, user_id: int) -> str | None:
        from app.modules.users.models import User
        user = await self.db.get(User, user_id)
        return user.username if user else None

    async def _freeze_shift(self, shift: CashierShift) -> None:
        if not await self.shift_uses_cash_ledger(shift):
            return
        existing = await self.db.scalar(
            select(ShiftCloseSnapshot.id).where(ShiftCloseSnapshot.shift_id == shift.id)
        )
        if existing:
            return
        report = await self.get_shifts_report(shift.target_date)
        row = next(item for item in report if item["id"] == shift.id)
        self.db.add(ShiftCloseSnapshot(
            shift_id=shift.id,
            opening_cash=Decimal(str(row["opening_cash"])),
            confirmed_cash=Decimal(str(row["confirmed_cash"])),
            unconfirmed_cash_sales=Decimal(str(row["unconfirmed_cash_sales"])),
            cash_expenses=Decimal(str(row["cash_expenses"])),
            expected_cash=Decimal(str(row["expected_cash"])),
            cashier_count=shift.actual_closing_cash,
            difference=(Decimal(str(row["cash_difference"])) if row["cash_difference"] is not None else None),
        ))
        await self.db.flush()

    async def start_shift(self, user_id: int, sync_web_orders: bool = False):
        target_date = get_business_date()
        # Serialize starts across cashiers so two logins cannot both see an
        # empty drawer and open overlapping shifts at the same time.
        if getattr(getattr(self.db, "bind", None), "dialect", None) is not None and self.db.bind.dialect.name == "postgresql":
            await self.db.execute(text("SELECT pg_advisory_xact_lock(1901226)"))
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
            # Keep an overnight shift accessible to its cashier for count and
            # close. Never silently close it without a physical cash count.
            return active_shift

        other_open = await self.db.scalar(select(CashierShift).where(
            CashierShift.end_time.is_(None),
        ).order_by(desc(CashierShift.id)))
        if other_open:
            raise ValidationError(f"شيفت #{other_open.id} ما زال مفتوحًا؛ أكمل تسويته قبل فتح شيفت جديد")

        unsettled = await self.db.scalar(select(CashierShift).outerjoin(
            ShiftCloseSnapshot, ShiftCloseSnapshot.shift_id == CashierShift.id,
        ).where(
            ShiftCloseSnapshot.id.is_not(None),
            CashierShift.end_time.is_not(None),
            ShiftCloseSnapshot.confirmed_at.is_(None),
        ).order_by(CashierShift.id))
        if unsettled:
            raise ValidationError(f"إدارة المطعم لم تعتمد تسليم شيفت #{unsettled.id} بعد")

        new_shift = CashierShift(
            user_id=user_id,
            target_date=target_date,
            start_time=datetime.now(UTC).replace(tzinfo=None),
            opening_cash=Decimal("300.00"),
            cash_tracking_enabled=True,
        )
        self.db.add(new_shift)
        await self.db.flush()
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
            uses_ledger = await self.shift_uses_cash_ledger(active_shift)
            if uses_ledger and active_shift.opening_confirmed_at is None:
                from app.core.exceptions import ValidationError
                raise ValidationError("أكد عهدة بداية الشيفت قبل إغلاقه")
            if uses_ledger and active_shift.actual_closing_cash is None:
                from app.core.exceptions import ValidationError
                raise ValidationError("سجل عدّ النقد الفعلي قبل إغلاق الشيفت")
            if uses_ledger:
                active_shift.cash_tracking_enabled = True
            active_shift.end_time = datetime.now(UTC).replace(tzinfo=None)
            await self.db.flush()
            await self._freeze_shift(active_shift)
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
            Order.id,
            Order.created_by_user_id,
            Order.created_at,
            Order.order_source,
            Order.order_status,
            Order.total_amount,
            Order.delivery_fee,
            Order.discount_amount,
            Order.payment_method,
            Order.order_type,
            Order.cash_tracking_enabled,
        ).where(
            or_(
                (Order.created_at >= start_local) & (Order.created_at < report_end_local),
                Order.id.in_(select(OrderStatusHistory.order_id).where(
                    OrderStatusHistory.status == OrderStatus.CONFIRMED,
                    OrderStatusHistory.changed_at >= start_local,
                    OrderStatusHistory.changed_at < report_end_local,
                    OrderStatusHistory.is_deleted == False,
                )),
            ),
            Order.is_deleted == False,
        )

        orders_result = await self.db.execute(orders_query)
        day_orders = orders_result.all()
        # Online orders belong to the shift that accepted them. Customer-created
        # timestamps can precede that shift (or even the business day).
        candidate_ids = [order.id for order in day_orders if getattr(order, "id", None) is not None]
        confirmation_times = {}
        if candidate_ids:
            confirmations = (await self.db.execute(select(
                OrderStatusHistory.order_id, OrderStatusHistory.changed_at,
            ).where(
                OrderStatusHistory.order_id.in_(candidate_ids),
                OrderStatusHistory.status == OrderStatus.CONFIRMED,
                OrderStatusHistory.is_deleted == False,
            ).order_by(OrderStatusHistory.changed_at, OrderStatusHistory.id))).all()
            for order_id, changed_at in confirmations:
                confirmation_times.setdefault(order_id, changed_at)
        tracked = any(getattr(shift, "cash_tracking_enabled", False) for shift in shifts) or any(getattr(order, "cash_tracking_enabled", False) for order in day_orders)
        order_ids = [order.id for order in day_orders] if tracked else []
        cash_movements_result = await self.db.execute(
            select(OrderCashMovement).where(
                (OrderCashMovement.order_id.in_(order_ids))
                | (OrderCashMovement.shift_id.in_([shift.id for shift in shifts]))
            )
        ) if tracked else None
        cash_movements = cash_movements_result.scalars().all() if cash_movements_result else []
        snapshots_result = await self.db.execute(
            select(ShiftCloseSnapshot).where(ShiftCloseSnapshot.shift_id.in_([shift.id for shift in shifts]))
        ) if tracked else None
        snapshots = {row.shift_id: row for row in snapshots_result.scalars().all()} if snapshots_result else {}
        adjustments_result = await self.db.execute(
            select(ShiftCashAdjustment).where(ShiftCashAdjustment.shift_id.in_([shift.id for shift in shifts]))
            .order_by(ShiftCashAdjustment.id)
        ) if tracked else None
        cash_adjustments = adjustments_result.scalars().all() if adjustments_result else []
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
                and shift_start_local <= (
                    confirmation_times.get(order.id, order.created_at)
                    if getattr(order, "order_source", None) == OrderSource.ONLINE
                    else order.created_at
                ) < shift_end_local
            ]
            successful = [order for order in shift_orders if order.order_status != OrderStatus.CANCELLED]
            ledger_mode = bool(getattr(shift, "cash_tracking_enabled", False) or (
                shift.end_time is None and (shift.target_date == get_current_business_date() or is_approved_cutover_shift(shift))
                and any(getattr(order, "cash_tracking_enabled", False) for order in shift_orders)
            ))
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
            delivery_cash_sales = sum(
                restaurant_sales_amount(order) for order in successful
                if order.payment_method == PaymentMethod.CASH and order.order_type == OrderType.DELIVERY
            )
            opening_cash = shift.opening_cash or 0
            cash_expenses = sum(
                (expense.amount or 0) for expense in day_expenses
                if expense.shift_id == shift.id and (
                    not getattr(shift, "cash_tracking_enabled", False) or getattr(expense, "paid_from", "legacy_unverified") == "shift_cash"
                )
            )
            confirmed_cash = sum(
                (movement.amount if movement.to_holder == "cashier" else -movement.amount)
                for movement in cash_movements if movement.shift_id == shift.id
                and "cashier" in (movement.from_holder, movement.to_holder)
            )
            unconfirmed_cash_sales = Decimal("0.00")
            unconfirmed_delivery_cash = Decimal("0.00")
            if ledger_mode:
                for order in successful:
                    if order.payment_method != PaymentMethod.CASH:
                        continue
                    due = restaurant_sales_amount(order)
                    paid_to_cashier = sum(
                        (movement.amount if movement.to_holder == "cashier" else -movement.amount)
                        for movement in cash_movements if movement.order_id == order.id
                        and (shift.end_time is None or movement.created_at <= shift.end_time)
                        and "cashier" in (movement.from_holder, movement.to_holder)
                    )
                    unconfirmed = max(Decimal("0.00"), due - paid_to_cashier)
                    unconfirmed_cash_sales += unconfirmed
                    if order.order_type == OrderType.DELIVERY:
                        unconfirmed_delivery_cash += unconfirmed
            # Collection movements document custody. The drawer expectation is
            # based on cash sales regardless of when someone attests receipt.
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
            snapshot = snapshots.get(shift.id)
            late_expenses = []
            shift_adjustments = [row for row in cash_adjustments if row.shift_id == shift.id]
            late_order_movements = []
            if snapshot:
                late_expenses = [
                    expense for expense in day_expenses
                    if expense.shift_id == shift.id and expense.paid_from == "shift_cash"
                    and expense.created_at > shift.end_time
                ]
                late_order_movements = [
                    movement for movement in cash_movements
                    if movement.shift_id == shift.id and movement.created_at > shift.end_time
                ]
                opening_cash = snapshot.opening_cash
                confirmed_cash = snapshot.confirmed_cash
                unconfirmed_cash_sales = snapshot.unconfirmed_cash_sales
                cash_expenses = snapshot.cash_expenses
                expected_cash = snapshot.expected_cash
                cash_difference = snapshot.difference
                adjusted_closing_cash = (
                    snapshot.cashier_count + sum((row.amount for row in shift_adjustments), Decimal("0.00"))
                    if snapshot.cashier_count is not None else None
                )
            difference_after_adjustments = (
                adjusted_closing_cash - expected_cash
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
                "delivery_cash_sales": float(delivery_cash_sales),
                "confirmed_cash": float(confirmed_cash),
                "unconfirmed_cash_sales": float(unconfirmed_cash_sales),
                "unconfirmed_delivery_cash": float(unconfirmed_delivery_cash),
                "cash_tracking_enabled": ledger_mode,
                "legacy_expenses_unverified": float(sum((expense.amount or 0) for expense in day_expenses if expense.shift_id == shift.id and expense.paid_from == "legacy_unverified")) if ledger_mode else 0.0,
                "close_snapshot_at": format_dt(snapshot.closed_at) if snapshot else None,
                "late_cash_expenses": float(sum((row.amount for row in late_expenses), Decimal("0.00"))),
                "late_order_cash_movements": [
                    {"id": row.id, "order_id": row.order_id, "from_holder": row.from_holder,
                     "to_holder": row.to_holder, "amount": float(row.amount),
                     "actor_id": row.actor_id, "created_at": format_dt(row.created_at)}
                    for row in late_order_movements
                ],
                "post_close_adjustments_total": float(sum((row.amount for row in shift_adjustments), Decimal("0.00"))),
                "post_close_adjustments": [
                    {"id": row.id, "amount": float(row.amount), "reason": row.reason,
                     "actor_id": row.actor_id, "created_at": format_dt(row.created_at)}
                    for row in shift_adjustments
                ],
                "admin_confirmed_at": format_dt(snapshot.confirmed_at) if snapshot else None,
                "admin_count": float(snapshot.admin_count) if snapshot and snapshot.admin_count is not None else None,
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
                "difference_after_adjustments": (
                    float(difference_after_adjustments)
                    if difference_after_adjustments is not None else None
                ),
                "closing_note": shift.closing_note,
                "duration_minutes": duration_minutes,
                "status": "active" if shift.end_time is None else "closed",
                "target_date": shift.target_date.isoformat()
            })
            
        return report
