from datetime import datetime, date, timedelta, timezone
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List, Dict, Any, Optional

from app.modules.shifts.models import CashierShift
from app.modules.orders.models import Order
from app.core.enums import UserRole, OrderStatus, OrderStatus
from app.core.logging import logger

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

    def _record_outbox_event(self, event_type: str, data: dict):
        import os
        import json
        if os.environ.get("RUNTIME_MODE") == "desktop":
            from app.modules.orders.models import OutboxEvent, OutboxEventStatus
            outbox_record = OutboxEvent(
                event_type=event_type,
                topic="shifts.local",
                payload=json.dumps(data, default=str),
                status=OutboxEventStatus.PENDING
            )
            self.db.add(outbox_record)

    def _shift_outbox_payload(
        self,
        shift: CashierShift,
        end_time: Optional[datetime] = None,
        *,
        for_update: bool = False,
        username: Optional[str] = None,
    ) -> dict:
        payload = {
            "id": shift.id,
            "user_id": shift.user_id,
            "username": username,
            "target_date": shift.target_date.isoformat(),
            "start_time": shift.start_time.isoformat() if shift.start_time else None,
        }
        if for_update:
            payload["end_time"] = end_time.isoformat() if end_time else None
        return payload

    async def _username_for(self, user_id: int) -> Optional[str]:
        from app.modules.users.models import User
        user = await self.db.get(User, user_id)
        return user.username if user else None

    async def start_shift(self, user_id: int):
        target_date = get_business_date()
        username = await self._username_for(user_id)
        
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
                self._record_outbox_event(
                    "SHIFT_UPDATED",
                    self._shift_outbox_payload(last_shift, for_update=True, username=username),
                )
                await self.db.commit()

                from app.core.events import get_outbox_sync_trigger
                get_outbox_sync_trigger().set()
            else:
                # Already open locally — re-assert active state on the cloud admin.
                self._record_outbox_event(
                    "SHIFT_UPDATED",
                    self._shift_outbox_payload(last_shift, for_update=True, username=username),
                )
                await self.db.commit()

                from app.core.events import get_outbox_sync_trigger
                get_outbox_sync_trigger().set()
        else:
            # Create a new shift since the last one belongs to someone else, or no shifts exist today
            new_shift = CashierShift(
                user_id=user_id,
                target_date=target_date,
                start_time=datetime.utcnow()
            )
            self.db.add(new_shift)
            await self.db.flush() # To get the ID
            
            self._record_outbox_event("SHIFT_CREATED", {
                "id": new_shift.id,
                "user_id": new_shift.user_id,
                "username": username,
                "target_date": new_shift.target_date.isoformat(),
                "start_time": new_shift.start_time.isoformat(),
            })
            await self.db.commit()
            
            from app.core.events import get_outbox_sync_trigger
            get_outbox_sync_trigger().set()

    async def end_shift(self, user_id: int):
        target_date = get_business_date()
        username = await self._username_for(user_id)
        
        query = select(CashierShift).where(
            CashierShift.user_id == user_id,
            CashierShift.target_date == target_date,
            CashierShift.end_time.is_(None)
        )
        result = await self.db.execute(query)
        active_shift = result.scalars().first()
        
        if active_shift:
            active_shift.end_time = datetime.utcnow()
            self._record_outbox_event(
                "SHIFT_UPDATED",
                self._shift_outbox_payload(
                    active_shift,
                    end_time=active_shift.end_time,
                    for_update=True,
                    username=username,
                ),
            )
            await self.db.commit()
            
            from app.core.events import get_outbox_sync_trigger
            get_outbox_sync_trigger().set()
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
            func.count(Order.id).label("total_orders"),
            # Cashier sales exclude delivery charges.
            func.sum(Order.total_amount - Order.delivery_fee).label("total_sales")
        ).where(
            Order.created_at >= start_local,
            Order.created_at < end_local,
            Order.is_deleted == False,
            Order.order_status != OrderStatus.CANCELLED
        ).group_by(Order.created_by_user_id)

        orders_result = await self.db.execute(orders_query)
        stats = {row.created_by_user_id: {"total_orders": row.total_orders, "total_sales": row.total_sales or 0.0} for row in orders_result}

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
            st = stats.get(shift.user_id, {"total_orders": 0, "total_sales": 0.0})
            report.append({
                "id": shift.id,
                "user_id": shift.user_id,
                "cashier_name": shift.user.full_name or shift.user.username,
                "start_time": format_dt(shift.start_time),
                "end_time": format_dt(shift.end_time),
                "total_orders": st["total_orders"],
                "total_sales": float(st["total_sales"]),
                "target_date": shift.target_date.isoformat()
            })
            
        return report
