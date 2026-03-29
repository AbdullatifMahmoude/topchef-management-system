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

    async def get_by_code(self, code: str) -> Offer:
        query = select(Offer).where(Offer.code == code)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def list_offers(self) -> list[Offer]:
        query = select(Offer)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def delete(self, offer: Offer):
        await self.db.delete(offer)
