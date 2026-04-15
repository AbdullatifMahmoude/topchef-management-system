from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.orders.service import OrderService
from app.modules.pricing.service import PricingService
from app.modules.offer.service import OfferService

async def get_offer_service(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
) -> OfferService:
    return OfferService(db, redis=redis)

async def get_pricing_service(
    db: AsyncSession = Depends(get_db),
    offer_service: OfferService = Depends(get_offer_service)
) -> PricingService:
    return PricingService(db, offer_service=offer_service)

async def get_order_service(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    pricing_service: PricingService = Depends(get_pricing_service),
    offer_service: OfferService = Depends(get_offer_service)
) -> OrderService:
    return OrderService(
        db, 
        redis=redis, 
        pricing_service=pricing_service, 
        offer_service=offer_service
    )
