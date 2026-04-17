from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
from app.modules.offer.models import Offer
from app.modules.offer.schemas import OfferCreate

class OfferRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, offer_data: OfferCreate) -> Offer:
        data = offer_data.model_dump()
        for key in ["valid_from", "valid_to"]:
            if isinstance(data.get(key), datetime):
                data[key] = data[key].replace(tzinfo=None)
        
        new_offer = Offer(**data)
        self.db.add(new_offer)
        return new_offer

    async def get_by_id(self, offer_id: int) -> Offer:
        query = select(Offer).where(Offer.offer_id == offer_id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_code(self, code: str, lock: bool = False) -> Offer:
        query = select(Offer).where(Offer.code == code)
        if lock:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_customer_usage_count(self, offer_id: int, customer_phone: str = None, cashier_id: int = None) -> int:
        from sqlalchemy import func
        from app.modules.offer.models import OfferUsage
        
        query = select(func.count(OfferUsage.usage_id)).where(OfferUsage.offer_id == offer_id)
        if customer_phone:
            query = query.where(OfferUsage.customer_phone == customer_phone)
        elif cashier_id:
            query = query.where(OfferUsage.cashier_id == cashier_id)
        else:
            return 0 # No identity to check
            
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def record_usage(self, usage_data: dict) -> None:
        from app.modules.offer.models import OfferUsage
        new_usage = OfferUsage(**usage_data)
        self.db.add(new_usage)

    async def list_offers(self, only_active: bool = False) -> list[Offer]:
        query = select(Offer)
        if only_active:
            query = query.where(Offer.is_active == True)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def delete(self, offer: Offer):
        await self.db.delete(offer)
