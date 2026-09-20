from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.business_calendar import (
    business_day_start,
    get_current_business_date,
    holiday_name,
    is_weekly_holiday,
    previous_business_date,
)
from app.core.enums import OrderSource, OrderStatus, OrderType
from app.modules.offer.models import OfferUsage
from app.modules.orders import models, schemas


def _offer_load_option():
    return selectinload(models.Order.offer_usage).selectinload(OfferUsage.offer)

class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_business_date(self) -> date:
        return get_current_business_date()


    async def get_by_id(self, order_id: int) -> models.Order | None:
        query = select(models.Order).options(
            selectinload(models.Order.items).selectinload(models.OrderItem.product),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            selectinload(models.Order.modifications),
            _offer_load_option()
        ).where(
            models.Order.id == order_id,
            models.Order.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_idempotency_key(self, key: str) -> models.Order | None:
        query = select(models.Order).options(
            selectinload(models.Order.items).selectinload(models.OrderItem.product),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            _offer_load_option()
        ).where(
            models.Order.idempotency_key == key,
            models.Order.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_number(self, order_number: str, order_date: date | None = None) -> models.Order | None:
        if order_date is None:
            order_date = self.get_business_date()
        query = select(models.Order).options(
            selectinload(models.Order.items).selectinload(models.OrderItem.product),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            _offer_load_option()
        ).where(
            models.Order.order_number == order_number,
            models.Order.order_date == order_date,
            models.Order.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def list_orders_paginated(
        self,
        source: OrderSource | None = None,
        status: OrderStatus | None = None,
        order_type: OrderType | None = None,
        page: int = 1,
        page_size: int = 50,
        cashier_id: int | None = None
    ) -> tuple[int, list[models.Order]]:

        """Get paginated orders."""
        query = select(models.Order).options(
            selectinload(models.Order.items).selectinload(models.OrderItem.product),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            selectinload(models.Order.modifications),
            _offer_load_option()
        ).where(models.Order.is_deleted == False)
        
        if source:
            query = query.where(models.Order.order_source == source)
        if status:
            query = query.where(models.Order.order_status == status)
        if order_type:
            query = query.where(models.Order.order_type == order_type)
            
        if cashier_id:
            from sqlalchemy import and_, or_
            query = query.where(
                or_(
                    and_(models.Order.order_source == OrderSource.CASHIER, models.Order.created_by_user_id == cashier_id),
                    models.Order.order_source == OrderSource.ONLINE,
                )
            )

        # Filter by the current business day.
        query = query.where(models.Order.order_date == self.get_business_date())

        
        # Count total
        count_query = select(func.count()).select_from(models.Order).where(models.Order.is_deleted == False)
        if source:
            count_query = count_query.where(models.Order.order_source == source)
        if status:
            count_query = count_query.where(models.Order.order_status == status)
        if order_type:
            count_query = count_query.where(models.Order.order_type == order_type)
            
        if cashier_id:
            count_query = count_query.where(
                or_(
                    and_(models.Order.order_source == OrderSource.CASHIER, models.Order.created_by_user_id == cashier_id),
                    models.Order.order_source == OrderSource.ONLINE,
                )
            )
            
        count_query = count_query.where(models.Order.order_date == self.get_business_date())
        
        total = await self.db.scalar(count_query) or 0
        
        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(desc(models.Order.created_at)).offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        return total, result.scalars().all()

    async def list_orders(
        self,
        source: OrderSource | None = None,
        status: OrderStatus | None = None,
        order_type: OrderType | None = None,
        cashier_id: int | None = None
    ) -> list[models.Order]:
        query = select(models.Order).options(
            selectinload(models.Order.items).selectinload(models.OrderItem.product),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            selectinload(models.Order.modifications),
            _offer_load_option()
        ).where(models.Order.is_deleted == False)
        if source:
            query = query.where(models.Order.order_source == source)
        if status:
            query = query.where(models.Order.order_status == status)
        if order_type:
            query = query.where(models.Order.order_type == order_type)

        if cashier_id:
            from sqlalchemy import and_, or_
            query = query.where(
                or_(
                    and_(models.Order.order_source == OrderSource.CASHIER, models.Order.created_by_user_id == cashier_id),
                    models.Order.order_source == OrderSource.ONLINE,
                )
            )

        # Filter by the current business day.
        query = query.where(models.Order.order_date == self.get_business_date())

        query = query.order_by(desc(models.Order.created_at))
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def list_dashboard_orders(
        self,
        source: OrderSource | None = None,
        status: OrderStatus | None = None,
        order_type: OrderType | None = None,
        cashier_id: int | None = None,
    ) -> list[models.Order]:
        """Load only relationships rendered by the operational dashboard."""
        query = select(models.Order).options(
            selectinload(models.Order.items).selectinload(models.OrderItem.product),
        ).where(
            models.Order.is_deleted == False,
            models.Order.order_date == self.get_business_date(),
        )
        if source:
            query = query.where(models.Order.order_source == source)
        if status:
            query = query.where(models.Order.order_status == status)
        if order_type:
            query = query.where(models.Order.order_type == order_type)
        if cashier_id:
            from sqlalchemy import and_, or_
            query = query.where(
                or_(
                    and_(
                        models.Order.order_source == OrderSource.CASHIER,
                        models.Order.created_by_user_id == cashier_id,
                    ),
                    models.Order.order_source == OrderSource.ONLINE,
                )
            )
        result = await self.db.execute(query.order_by(desc(models.Order.created_at)))
        return result.scalars().all()

    async def get_next_order_number(self) -> str:
        """Atomically increment the per-terminal, per-business-day counter."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.core.config import settings
        from app.core.exceptions import ValidationError
        
        business_date = self.get_business_date()
        prefix = settings.TERMINAL_ID
        
        bind = self.db.bind
        if bind is not None and bind.dialect.name == "sqlite":
            count_query = select(func.count()).select_from(models.Order).where(
                models.Order.order_date == business_date,
                models.Order.is_deleted == False
            )
            current_count = await self.db.scalar(count_query) or 0
            return f"{prefix}-{current_count + 1:04d}"

        try:
            statement = pg_insert(models.DailyOrderCounter).values(
                business_date=business_date,
                terminal_id=prefix,
                last_value=1,
            )
            statement = statement.on_conflict_do_update(
                index_elements=["business_date", "terminal_id"],
                set_={"last_value": models.DailyOrderCounter.last_value + 1},
            ).returning(models.DailyOrderCounter.last_value)
            counter = (await self.db.execute(statement)).scalar_one()
            return f"{prefix}-{counter:04d}"
        except Exception as exc:
            raise ValidationError("Failed to generate order number") from exc

    async def save_in_transaction(self, order: models.Order) -> models.Order:
        """Adds to session without explicit commit (delegates to context manager)."""
        self.db.add(order)
        await self.db.flush()
        return order

    async def save(self, order: models.Order) -> models.Order:
        """Persist without committing; the request unit of work owns commit."""
        self.db.add(order)
        await self.db.flush()
        return order

    async def update(self, order: models.Order, update_data: schemas.OrderUpdate, changed_by_user_id: int | None = None) -> models.Order:
        """
        Update order status and related fields - database operations only.
        Assumes all validation has been done in the service layer.
        Does NOT commit - transaction management is handled by service layer.
        """
        old_status = order.order_status
        update_dict = update_data.model_dump(exclude_unset=True)
        new_status = update_dict.get('order_status')
        
        for field, value in update_dict.items():
            setattr(order, field, value)
        
        tz = timezone(timedelta(hours=3))
        order.updated_at = datetime.now(tz).replace(tzinfo=None)
        
        # Record history if status changed
        if new_status is not None and old_status != new_status:
            history = models.OrderStatusHistory(
                order_id=order.id,
                status=new_status,
                changed_by_user_id=changed_by_user_id
            )
            self.db.add(history)
        
        self.db.add(order)
        return order

    async def update_order_full(self, order: models.Order, update_data: schemas.OrderUpdateFull, changed_by_user_id: int | None = None) -> models.Order:
        """
        Comprehensive order update - database operations only.
        Assumes all validation has been done in the service layer.
        Does NOT commit - transaction management is handled by service layer.
        """
        update_dict = update_data.model_dump(exclude_unset=True, exclude={"items", "customer_address"})
        
        # Update all provided fields
        for field, value in update_dict.items():
            if value is None and field in ["order_type", "subtotal", "total_amount"]:
                continue
            setattr(order, field, value)
        
        # Update timestamp
        tz = timezone(timedelta(hours=3))
        order.updated_at = datetime.now(tz).replace(tzinfo=None)
        
        self.db.add(order)
        return order

    async def get_today_stats(self) -> dict:
        """Fetch aggregate stats for the current business shift."""
        business_date = self.get_business_date()
        
        query = select(
            func.count(models.Order.id).label("total_count"),
            # Dashboard sales use the same net-sales definition as reports and
            # cashier shifts: delivery fees are excluded.
            func.sum(
                models.Order.total_amount
                - case((models.Order.order_type == OrderType.DELIVERY, models.Order.delivery_fee), else_=0)
            ).filter(
                models.Order.order_status.in_([OrderStatus.COMPLETED, OrderStatus.DELIVERED, OrderStatus.NEW, OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY])
            ).label("total_sales"),
            func.count(models.Order.id).filter(models.Order.order_status.in_([OrderStatus.COMPLETED, OrderStatus.DELIVERED])).label("completed_count"),
            func.count(models.Order.id).filter(models.Order.order_status == OrderStatus.CANCELLED).label("cancelled_count"),
        ).where(
            models.Order.order_date == business_date,
            models.Order.is_deleted == False
        )
        
        result = await self.db.execute(query)
        row = result.mappings().first()
        
        # Also get active orders (new or confirmed)
        active_query = select(func.count(models.Order.id)).where(
            models.Order.order_date == business_date,
            models.Order.is_deleted == False,
            models.Order.order_status.in_([OrderStatus.NEW, OrderStatus.CONFIRMED])
        )
        active_count = await self.db.scalar(active_query) or 0

        # Compare like-for-like from the business-day cutoff to the same elapsed
        # point in its business day, rather than yesterday's completed day.
        local_now = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
        today_start = business_day_start(business_date)
        elapsed = max(timedelta(0), local_now - today_start)
        comparison_date = previous_business_date(business_date)
        comparison_start = business_day_start(comparison_date)
        comparison_cutoff = comparison_start + min(elapsed, timedelta(days=1))
        yesterday_sales_query = select(
            func.sum(
                models.Order.total_amount
                - case((models.Order.order_type == OrderType.DELIVERY, models.Order.delivery_fee), else_=0)
            )
        ).where(
            models.Order.order_date == comparison_date,
            models.Order.created_at >= comparison_start,
            models.Order.created_at < comparison_cutoff,
            models.Order.is_deleted == False,
            models.Order.order_status.in_([
                OrderStatus.COMPLETED,
                OrderStatus.DELIVERED,
                OrderStatus.NEW,
                OrderStatus.CONFIRMED,
                OrderStatus.OUT_FOR_DELIVERY,
            ]),
        )
        yesterday_sales = float(await self.db.scalar(yesterday_sales_query) or 0)
        today_sales = float(row["total_sales"] or 0)
        from app.modules.shifts.models import ShiftExpense
        today_expenses = float(await self.db.scalar(select(func.sum(ShiftExpense.amount)).where(
            ShiftExpense.target_date == business_date,
            ShiftExpense.is_deleted == False,
        )) or 0)
        sales_change_percent = (
            ((today_sales - yesterday_sales) / yesterday_sales) * 100
            if yesterday_sales > 0 else None
        )
        
        return {
            "total_count": row["total_count"] or 0,
            "total_sales": today_sales,
            "total_expenses": today_expenses,
            "net_profit": today_sales - today_expenses,
            "yesterday_sales": yesterday_sales,
            "sales_change_percent": sales_change_percent,
            "comparison_date": comparison_date.isoformat(),
            "comparison_label": "آخر يوم تشغيل" if comparison_date != business_date - timedelta(days=1) else "أمس",
            "completed_count": row["completed_count"] or 0,
            "cancelled_count": row["cancelled_count"] or 0,
            "active_count": active_count,
            "is_holiday": is_weekly_holiday(business_date),
            "holiday_name": holiday_name(business_date),
        }
