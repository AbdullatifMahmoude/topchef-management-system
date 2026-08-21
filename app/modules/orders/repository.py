from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from datetime import date, timedelta, datetime, timezone
from typing import Optional, List, Tuple
from app.modules.orders import models, schemas
from app.core.enums import OrderSource, OrderStatus, OrderType
from app.core.business_calendar import holiday_name, is_weekly_holiday, previous_business_date

class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_business_date(self) -> date:
        # Business shift starts at 5am (UTC+3)
        tz = timezone(timedelta(hours=3))
        now = datetime.now(tz)
        if now.hour < 5:
            return (now - timedelta(days=1)).date()
        return now.date()


    async def get_by_id(self, order_id: int) -> Optional[models.Order]:
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            selectinload(models.Order.modifications)
        ).where(
            models.Order.id == order_id,
            models.Order.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_idempotency_key(self, key: str) -> Optional[models.Order]:
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address)
        ).where(
            models.Order.idempotency_key == key,
            models.Order.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_number(self, order_number: str, order_date: Optional[date] = None) -> Optional[models.Order]:
        if order_date is None:
            order_date = self.get_business_date()
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address)
        ).where(
            models.Order.order_number == order_number,
            models.Order.order_date == order_date,
            models.Order.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def list_orders_paginated(
        self,
        source: Optional[OrderSource] = None,
        status: Optional[OrderStatus] = None,
        order_type: Optional[OrderType] = None,
        page: int = 1,
        page_size: int = 50,
        cashier_id: Optional[int] = None
    ) -> Tuple[int, List[models.Order]]:

        """Get paginated orders."""
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            selectinload(models.Order.modifications)
        ).where(models.Order.is_deleted == False)
        
        if source:
            query = query.where(models.Order.order_source == source)
        if status:
            query = query.where(models.Order.order_status == status)
        if order_type:
            query = query.where(models.Order.order_type == order_type)
            
        if cashier_id:
            from sqlalchemy import or_, and_
            query = query.where(
                or_(
                    and_(models.Order.order_source == OrderSource.CASHIER, models.Order.created_by_user_id == cashier_id),
                    models.Order.order_source == OrderSource.ONLINE,
                )
            )

        # Filter by current business shift (24h starting at 5am)
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
        source: Optional[OrderSource] = None,
        status: Optional[OrderStatus] = None,
        order_type: Optional[OrderType] = None,
        cashier_id: Optional[int] = None
    ) -> List[models.Order]:
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person),
            selectinload(models.Order.address),
            selectinload(models.Order.modifications)
        ).where(models.Order.is_deleted == False)
        if source:
            query = query.where(models.Order.order_source == source)
        if status:
            query = query.where(models.Order.order_status == status)
        if order_type:
            query = query.where(models.Order.order_type == order_type)

        if cashier_id:
            from sqlalchemy import or_, and_
            query = query.where(
                or_(
                    and_(models.Order.order_source == OrderSource.CASHIER, models.Order.created_by_user_id == cashier_id),
                    models.Order.order_source == OrderSource.ONLINE,
                )
            )

        # Filter by current business shift (24h starting at 5am)
        query = query.where(models.Order.order_date == self.get_business_date())

        query = query.order_by(desc(models.Order.created_at))
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_next_order_number(self) -> str:
        """Get next order number using a daily PostgreSQL sequence (atomic)."""
        from sqlalchemy import text
        from app.core.database import engine
        from app.core.logging import logger
        from app.core.exceptions import ValidationError
        from app.core.config import settings
        
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

        seq_name = f"order_seq_{business_date.strftime('%Y_%m_%d')}"
        
        try:
            # Use a savepoint so if the sequence doesn't exist, it doesn't abort the outer transaction
            async with self.db.begin_nested():
                result = await self.db.execute(text(f"SELECT nextval('{seq_name}')"))
                seq_value = result.scalar()
                return f"{prefix}-{seq_value:04d}"
        except Exception as e:
            # If sequence doesn't exist for the day, try to create it
            if seq_name in str(e).lower() or "does not exist" in str(e).lower() or "relation" in str(e).lower():
                try:
                    logger.info(f"Sequence '{seq_name}' missing. Creating via main connection...")
                    async with self.db.begin_nested():
                        await self.db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START WITH 1"))
                    
                    # Retry after creation on the main transaction
                    result = await self.db.execute(text(f"SELECT nextval('{seq_name}')"))
                    seq_value = result.scalar()
                    return f"{prefix}-{seq_value:04d}"
                except Exception as create_err:
                    logger.error(f"Critical: Failed to self-heal sequence: {create_err}")
            
            logger.error(f"Error generating order number: {e}")
            raise ValidationError("Failed to generate order number")

    async def save_in_transaction(self, order: models.Order) -> models.Order:
        """Adds to session without explicit commit (delegates to context manager)."""
        self.db.add(order)
        await self.db.flush()
        return order

    async def save(self, order: models.Order) -> models.Order:
        self.db.add(order)
        try:
            await self.db.commit()
            await self.db.refresh(order)
            return order
        except Exception:
            await self.db.rollback()
            raise

    async def update(self, order: models.Order, update_data: schemas.OrderUpdate, changed_by_user_id: Optional[int] = None) -> models.Order:
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
        if old_status != new_status:
            history = models.OrderStatusHistory(
                order_id=order.id,
                status=new_status,
                changed_by_user_id=changed_by_user_id
            )
            self.db.add(history)
        
        self.db.add(order)
        return order

    async def update_order_full(self, order: models.Order, update_data: schemas.OrderUpdateFull, changed_by_user_id: Optional[int] = None) -> models.Order:
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
            func.sum(models.Order.total_amount - models.Order.delivery_fee).filter(
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

        # Compare like-for-like: yesterday from 5 AM up to the same elapsed
        # point in its business day, rather than yesterday's completed day.
        local_now = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
        today_start = datetime.combine(business_date, datetime.min.time()).replace(hour=5)
        elapsed = max(timedelta(0), local_now - today_start)
        comparison_date = previous_business_date(business_date)
        comparison_start = datetime.combine(comparison_date, datetime.min.time()).replace(hour=5)
        comparison_cutoff = comparison_start + min(elapsed, timedelta(days=1))
        yesterday_sales_query = select(
            func.sum(models.Order.total_amount - models.Order.delivery_fee)
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
