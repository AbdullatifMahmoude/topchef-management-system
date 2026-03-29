import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.offer.repository import OfferRepository
from app.modules.offer.schemas import OfferCreate, OfferUpdate, OfferResponse
from typing import List, Optional
from app.core.logging import logger

class OfferService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis
        self.repository = OfferRepository(db)

    async def _invalidate_cache(self):
        if self.redis:
            try:
                await self.redis.delete("offers:all")
            except Exception as e:
                logger.warning(f"Redis error invalidating offers cache: {e}")

    async def create_offer(self, offer_data: OfferCreate) -> OfferResponse:
        async with self.db.begin():
            existing_offer = await self.repository.get_by_code(offer_data.code)
            if existing_offer:
                raise ValidationError(f"Offer with code '{offer_data.code}' already exists")
            
            offer = await self.repository.create(offer_data)
            await self.db.flush()
            logger.info(f"Offer created: code='{offer.code}', type='{offer.discount_type}'")
            await self._invalidate_cache()
        
        return OfferResponse.model_validate(offer)

    async def list_all_offers(self) -> List[OfferResponse]:
        cache_key = "offers:all"
        
        # 1. Try Cache
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return [OfferResponse(**item) for item in data]
            except Exception as e:
                logger.warning(f"Redis error reading offers: {e}")

        # 2. DB Fallback
        async with self.db.begin():
            offers = await self.repository.list_offers()
            for offer in offers:
                was_deactivated = offer.deactivate_if_expired()
                if was_deactivated:
                     logger.info(f"Offer code '{offer.code}' deactivated automatically in list due to expiration.")
            
            await self.db.flush()
            response = [OfferResponse.model_validate(offer) for offer in offers]

            # 3. Save to Cache (5 minutes)
            if self.redis:
                try:
                    serializable = [o.model_dump(mode='json') for o in response]
                    await self.redis.setex(cache_key, 300, json.dumps(serializable))
                except Exception as e:
                    logger.warning(f"Redis error writing offers cache: {e}")
        
        return response

    async def get_offer_by_id(self, offer_id: int, check_cache: bool = True) -> OfferResponse:
        # 1. Hybrid Cache Path
        if check_cache and self.redis:
            try:
                offers = await self.list_all_offers()
                for offer in offers:
                    if offer.offer_id == offer_id:
                        # Extra check: If it was cached but just expired, don't return as active
                        if offer.is_active and offer.valid_to < datetime.utcnow():
                            break # Fallback to DB to handle deactivation
                        return offer
            except Exception as e:
                logger.warning(f"Redis hybrid search error for offer {offer_id}: {e}")

        # 2. Database Path
        async with self.db.begin():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            # Use Rich Model method directly
            was_deactivated = offer.deactivate_if_expired()
            if was_deactivated:
                logger.info(f"Offer code '{offer.code}' deactivated automatically on access due to expiration.")
                await self.db.flush()
                await self._invalidate_cache()
        
        return OfferResponse.model_validate(offer)

    async def get_offer_by_code(self, code: str, check_cache: bool = True) -> OfferResponse:
        # 1. Hybrid Cache Path
        if check_cache and self.redis:
            try:
                offers = await self.list_all_offers()
                for offer in offers:
                    if offer.code == code:
                        if offer.is_active and offer.valid_to < datetime.utcnow():
                            break # Fallback to DB
                        return offer
            except Exception as e:
                logger.warning(f"Redis hybrid search error for offer code {code}: {e}")

        # 2. Database Path
        async with self.db.begin():
            offer = await self.repository.get_by_code(code)
            if not offer:
                raise NotFoundError(f"Offer code '{code}'")
            
            was_deactivated = offer.deactivate_if_expired()
            if was_deactivated:
                 logger.info(f"Offer code '{offer.code}' deactivated automatically on access due to expiration.")
                 await self.db.flush()
                 await self._invalidate_cache()
        
        return OfferResponse.model_validate(offer)

    async def update_offer(self, offer_id: int, offer_data: OfferUpdate) -> OfferResponse:
        async with self.db.begin():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            # Map update data via model's rich method
            update_dict = offer_data.model_dump(exclude_unset=True)
            for key in ["valid_from", "valid_to"]:
                if isinstance(update_dict.get(key), datetime):
                    update_dict[key] = update_dict[key].replace(tzinfo=None)
            
            offer.update_info(update_dict)
            
            await self.db.flush()
            logger.info(f"Offer updated: id={offer_id}, code='{offer.code}'")
            await self._invalidate_cache()
        
        return OfferResponse.model_validate(offer)

    async def delete_offer(self, offer_id: int) -> bool:
        async with self.db.begin():
            offer = await self.repository.get_by_id(offer_id)
            if not offer:
                raise NotFoundError(f"Offer with id:{offer_id}")
            
            await self.repository.delete(offer)
            logger.info(f"Offer deleted: id={offer_id}")
            await self._invalidate_cache()
        return True
