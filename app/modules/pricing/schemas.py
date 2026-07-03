from pydantic import BaseModel, Field
from typing import List, Optional
from decimal import Decimal
from app.core.enums import OrderType, OrderSource, DiscountType

class PricingItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)

class PricingRequest(BaseModel):
    items: List[PricingItem]
    order_type: OrderType
    source: OrderSource = OrderSource.ONLINE
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    offer_code: Optional[str] = None
    customer_phone: Optional[str] = None
    cashier_id: Optional[int] = None
    manual_discount_type: Optional[DiscountType] = None
    manual_discount_value: Optional[Decimal] = None

class PricingResult(BaseModel):
    subtotal: Decimal
    discount_amount: Decimal
    delivery_fee: Decimal
    total_amount: Decimal
