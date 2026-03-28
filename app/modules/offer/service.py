from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.offer.repository import OfferRepository
from app.modules.offer.schemas import OfferCreate, OfferUpdate, OfferResponse
from typing import List, Optional
from app.core.logging import logger

class OfferService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = OfferRepository(db)

    async def create_offer(self, offer_data: OfferCreate) -> OfferResponse:
        async with self.db.begin():
            existing_offer = await self.repository.get_by_code(offer_data.code)
            if existing_offer:
                raise ValidationError(f"Offer with code '{offer_data.code}' already exists")
            
            offer = await self.repository.create(offer_data)
            await self.db.flush()
            logger.info(f"Offer created: code='{offer.code}', type='{offer.discount_type}'")
        
        return OfferResponse.model_validate(offer)

    async def get_offer_by_id(self, offer_id: int) -> OfferResponse:
        async with self.db.begin():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            # Use Rich Model method directly
            was_deactivated = offer.deactivate_if_expired()
            if was_deactivated:
                logger.info(f"Offer code '{offer.code}' deactivated automatically on access due to expiration.")
                await self.db.flush()
        
        return OfferResponse.model_validate(offer)

    async def get_offer_by_code(self, code: str) -> OfferResponse:
        async with self.db.begin():
            offer = await self.repository.get_by_code(code)
            if not offer:
                raise NotFoundError(f"Offer code '{code}'")
            
            was_deactivated = offer.deactivate_if_expired()
            if was_deactivated:
                 logger.info(f"Offer code '{offer.code}' deactivated automatically on access due to expiration.")
                 await self.db.flush()
        
        return OfferResponse.model_validate(offer)

    async def list_all_offers(self) -> List[OfferResponse]:
        async with self.db.begin():
            offers = await self.repository.list_offers()
            for offer in offers:
                was_deactivated = offer.deactivate_if_expired()
                if was_deactivated:
                     logger.info(f"Offer code '{offer.code}' deactivated automatically in list due to expiration.")
            
            await self.db.flush()
        
        return [OfferResponse.model_validate(offer) for offer in offers]

    async def update_offer(self, offer_id: int, offer_data: OfferUpdate) -> OfferResponse:
        async with self.db.begin():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            # Map update data via model's rich method
            update_dict = offer_data.model_dump(exclude_unset=True)
            offer.update_info(update_dict)
            
            await self.db.flush()
            logger.info(f"Offer updated: id={offer_id}, code='{offer.code}'")
        
        return OfferResponse.model_validate(offer)

    async def delete_offer(self, offer_id: int) -> bool:
        async with self.db.begin():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            await self.repository.delete(offer)
            logger.info(f"Offer deleted: id={offer_id}")
        return True
