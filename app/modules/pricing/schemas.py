from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.core.enums import DiscountType, OrderSource, OrderType


class PricingItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)

class PricingRequest(BaseModel):
    items: list[PricingItem]
    order_type: OrderType
    source: OrderSource = OrderSource.ONLINE
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    offer_code: str | None = None
    customer_phone: str | None = None
    cashier_id: int | None = None
    redeemed_order_id: int | None = None
    manual_discount_type: DiscountType | None = None
    manual_discount_value: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_discount_rules(self):
        if (self.manual_discount_type is None) != (self.manual_discount_value is None):
            raise ValueError("Manual discount type and value must be provided together")
        if self.manual_discount_type == DiscountType.PERCENTAGE and self.manual_discount_value > Decimal(100):
            raise ValueError("Manual percentage discount cannot exceed 100%")
        if self.offer_code and self.manual_discount_type:
            raise ValueError("An offer and a manual discount cannot be combined")
        return self

class PricingResult(BaseModel):
    subtotal: Decimal
    discount_amount: Decimal
    delivery_fee: Decimal
    total_amount: Decimal
