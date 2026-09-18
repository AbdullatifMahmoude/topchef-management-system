from pydantic import BaseModel, Field, model_validator
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
    redeemed_order_id: Optional[int] = None
    manual_discount_type: Optional[DiscountType] = None
    manual_discount_value: Optional[Decimal] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_discount_rules(self):
        if (self.manual_discount_type is None) != (self.manual_discount_value is None):
            raise ValueError("Manual discount type and value must be provided together")
        if self.manual_discount_type == DiscountType.PERCENTAGE and self.manual_discount_value > Decimal("100"):
            raise ValueError("Manual percentage discount cannot exceed 100%")
        if self.offer_code and self.manual_discount_type:
            raise ValueError("An offer and a manual discount cannot be combined")
        return self

class PricingResult(BaseModel):
    subtotal: Decimal
    discount_amount: Decimal
    delivery_fee: Decimal
    total_amount: Decimal
