from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from datetime import date, timedelta, datetime, timezone
from typing import Optional, List, Tuple
from app.modules.orders import models, schemas
from app.core.enums import OrderSource, OrderStatus, OrderType

class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_business_date(self) -> date:
        # Force UTC+2 (Local Time for Egypt/Palestine)
        tz = timezone(timedelta(hours=2))
        return datetime.now(tz).date()


    async def get_by_id(self, order_id: int) -> Optional[models.Order]:
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person)
        ).where(models.Order.id == order_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_idempotency_key(self, key: str) -> Optional[models.Order]:
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person)
        ).where(
            models.Order.idempotency_key == key
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_number(self, order_number: str, order_date: Optional[date] = None) -> Optional[models.Order]:
        if order_date is None:
            order_date = date.today()
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person)
        ).where(
            models.Order.order_number == order_number,
            models.Order.order_date == order_date
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def list_orders_paginated(
        self,
        source: Optional[OrderSource] = None,
        status: Optional[OrderStatus] = None,
        order_type: Optional[OrderType] = None,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[int, List[models.Order]]:

        """Get paginated orders."""
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person)
        )
        
        if source:
            query = query.where(models.Order.order_source == source)
        if status:
            query = query.where(models.Order.order_status == status)
        if order_type:
            query = query.where(models.Order.order_type == order_type)

        # Filter by current business shift (24h starting at 5am)
        query = query.where(models.Order.order_date == self.get_business_date())

        
        # Count total
        count_query = select(func.count()).select_from(models.Order)
        if source:
            count_query = count_query.where(models.Order.order_source == source)
        if status:
            count_query = count_query.where(models.Order.order_status == status)
        if order_type:
            count_query = count_query.where(models.Order.order_type == order_type)
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
        order_type: Optional[OrderType] = None
    ) -> List[models.Order]:
        query = select(models.Order).options(
            selectinload(models.Order.items),
            selectinload(models.Order.creator),
            selectinload(models.Order.delivery_person)
        )
        if source:
            query = query.where(models.Order.order_source == source)
        if status:
            query = query.where(models.Order.order_status == status)
        if order_type:
            query = query.where(models.Order.order_type == order_type)

        # Filter by current business shift (24h starting at 5am)
        query = query.where(models.Order.order_date == self.get_business_date())

        query = query.order_by(desc(models.Order.created_at))
        
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_next_order_number(self) -> str:
        """Get next order number using PostgreSQL sequence (atomic)."""
        from sqlalchemy import text
        from app.core.database import engine
        from app.core.logging import logger
        from app.core.exceptions import ValidationError
        
        try:
            # Try to get next value
            result = await self.db.execute(text("SELECT nextval('order_number_seq')"))
            seq_value = result.scalar()
            return f"{seq_value:04d}"
        except Exception as e:
            # If sequence doesn't exist, try to create it using a separate connection
            # because the current transaction is now 'aborted'.
            if "order_number_seq" in str(e).lower():
                try:
                    logger.info("Sequence 'order_number_seq' missing. Creating via independent connection...")
                    async with engine.begin() as conn:
                        await conn.execute(text("CREATE SEQUENCE IF NOT EXISTS order_number_seq START WITH 1"))
                    
                    # Manual rollback of the failed transaction in the current session
                    # so we can reuse the session for the retry
                    await self.db.rollback()
                    
                    # Retry after creation
                    result = await self.db.execute(text("SELECT nextval('order_number_seq')"))
                    seq_value = result.scalar()
                    return f"{seq_value:04d}"
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
        old_status = order.order_status
        update_dict = update_data.model_dump(exclude_unset=True)
        new_status = update_dict.get('order_status')
        if new_status and old_status != new_status:
            from app.core.exceptions import ValidationError
            if not order.can_transition_to(new_status):
                raise ValidationError(f"Invalid status transition from {old_status} to {new_status}")
        
        for field, value in update_dict.items():
            setattr(order, field, value)
        
        tz = timezone(timedelta(hours=2))
        order.updated_at = datetime.now(tz).replace(tzinfo=None)
        
        # Record history if status changed
        if old_status != new_status:
            history = models.OrderStatusHistory(
                order_id=order.id,
                status=new_status,
                changed_by_user_id=changed_by_user_id
            )
            self.db.add(history)

        try:
            await self.db.commit()
            await self.db.refresh(order)
            return order
        except Exception:
            await self.db.rollback()
            raise
