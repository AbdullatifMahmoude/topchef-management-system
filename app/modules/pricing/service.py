from decimal import Decimal
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.pricing.schemas import PricingRequest, PricingResult
from app.core.enums import OrderType, DiscountType
from app.modules.offer.service import OfferService
from app.modules.pricing.domain import FinancialSnapshot

from app.core.protocols import OfferServiceInterface

class PricingService:
    def __init__(self, db: AsyncSession, offer_service: Optional[OfferServiceInterface] = None):
        self.db = db
        # If not provided, we can still fallback or raise error depending on policy
        # However, for Clean Architecture, explicit injection is better.
        self.offer_service = offer_service or OfferService(db)

    async def calculate_price(self, request: PricingRequest) -> PricingResult:
        # 1. Calculate raw subtotal from items
        subtotal = sum((item.quantity * item.unit_price) for item in request.items)
        subtotal = Decimal(str(subtotal))

        discount_amount = Decimal("0.00")
        
        # 2. Apply Offer if present
        if request.offer_code:
            offer_response = await self.offer_service.apply_offer(
                request.offer_code, 
                subtotal,
                request.items,
                request.customer_phone,
                request.cashier_id,
                commit_usage=False # This is a price calculation preview
            )
            discount_amount = offer_response.discount_amount

        # 2b. Apply manual discount if present (cashier-entered)
        if request.manual_discount_type and request.manual_discount_value and request.manual_discount_value > 0:
            if request.manual_discount_type == DiscountType.PERCENTAGE:
                manual_disc = (subtotal * request.manual_discount_value) / Decimal("100")
            else:  # fixed
                manual_disc = request.manual_discount_value
            discount_amount = discount_amount + min(manual_disc, subtotal - discount_amount)

        # 3. Handle Delivery Fee
        delivery_fee = Decimal("0.00")
        if request.order_type in (OrderType.DELIVERY, OrderType.HALL):
            delivery_fee = request.delivery_fee
            if delivery_fee < 0:
                raise ValueError("Delivery fee cannot be negative")
        
        # 4. Consolidate using FinancialSnapshot (Pure Logic)
        snapshot = FinancialSnapshot.calculate(
            subtotal=subtotal,
            discount_amount=discount_amount,
            delivery_fee=delivery_fee
        )
        
        return PricingResult(
            subtotal=snapshot.subtotal,
            discount_amount=snapshot.discount_amount,
            delivery_fee=snapshot.delivery_fee,
            total_amount=snapshot.total_amount
        )
