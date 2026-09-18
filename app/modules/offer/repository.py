from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime
from app.modules.offer.models import Offer
from app.modules.offer.schemas import OfferCreate

class OfferRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, offer_data: OfferCreate) -> Offer:
        data = offer_data.model_dump()
        data.pop("product_ids", None)
        # SQLAlchemy column defaults are applied on INSERT/flush, while offer
        # validation runs before that. Initialise the counter explicitly so a
        # brand-new offer is never compared as None against its usage limit.
        data.setdefault("current_usage", 0)
        for key in ["valid_from", "valid_to"]:
            if isinstance(data.get(key), datetime):
                data[key] = data[key].replace(tzinfo=None)
        
        new_offer = Offer(**data)
        self.db.add(new_offer)
        return new_offer

    async def get_by_id(self, offer_id: int) -> Offer:
        query = select(Offer).options(selectinload(Offer.products)).where(
            Offer.offer_id == offer_id,
            Offer.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_code(self, code: str, lock: bool = False) -> Offer:
        query = select(Offer).options(selectinload(Offer.products)).where(
            Offer.code == code,
            Offer.is_deleted == False
        )
        if lock:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_customer_usage_count(self, offer_id: int, customer_phone: str = None) -> int:
        from sqlalchemy import func
        from app.modules.offer.models import OfferUsage
        
        query = select(func.count(OfferUsage.usage_id)).where(OfferUsage.offer_id == offer_id)
        if customer_phone:
            query = query.where(OfferUsage.customer_phone == customer_phone)
        else:
            return 0 # No identity to check
            
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def record_usage(self, usage_data: dict) -> None:
        from app.modules.offer.models import OfferUsage
        new_usage = OfferUsage(**usage_data)
        self.db.add(new_usage)

    async def list_offers(self, only_active: bool = False) -> list[Offer]:
        query = select(Offer).options(selectinload(Offer.products)).where(Offer.is_deleted == False)
        if only_active:
            query = query.where(Offer.is_active == True)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def usage_analytics(self, start_utc: datetime, end_utc: datetime, limit: int = 12):
        from sqlalchemy import func
        from app.modules.offer.models import OfferUsage
        from app.modules.orders.models import Order
        from app.core.enums import OrderStatus
        from app.modules.users.models import User
        summary = await self.db.execute(
            select(
                func.count(OfferUsage.usage_id),
                func.coalesce(func.sum(OfferUsage.discount_amount), 0),
            )
            .join(Order, Order.id == OfferUsage.order_id)
            .where(
                OfferUsage.applied_at >= start_utc,
                OfferUsage.applied_at < end_utc,
                Order.order_status != OrderStatus.CANCELLED,
                Order.is_deleted == False,
            )
        )
        count, total = summary.one()
        rows = (await self.db.execute(
            select(OfferUsage, Offer.display_name, Offer.code, User.full_name)
            .join(Offer, Offer.offer_id == OfferUsage.offer_id)
            .join(Order, Order.id == OfferUsage.order_id)
            .outerjoin(User, User.id == OfferUsage.cashier_id)
            .where(
                Order.order_status != OrderStatus.CANCELLED,
                Order.is_deleted == False,
            )
            .order_by(OfferUsage.applied_at.desc())
            .limit(limit)
        )).all()
        return int(count or 0), total or 0, rows

    async def delete(self, offer: Offer):
        import time
        ts = int(time.time())
        offer.is_deleted = True
        offer.code = f"{offer.code}_deleted_{ts}"
