from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.enums import (
    DiscountType,
    OrderSource,
    OrderStatus,
    OrderType,
    PaymentMethod,
)
from app.modules.customer.schemas import CustomerAddressResponse


class OrderItemBase(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemResponse(OrderItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    total_price: Decimal
    product_name: str | None = None

class AppliedOfferResponse(BaseModel):
    code: str
    display_name: str | None = None
    discount_type: DiscountType
    discount_value: Decimal
    discount_amount: Decimal
    rules: dict[str, Any] = Field(default_factory=dict)

class OrderBase(BaseModel):
    customer_id: int | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    order_type: OrderType
    source: OrderSource = Field(OrderSource.ONLINE, validation_alias=AliasChoices("source", "order_source"))
    customer_notes: str | None = None
    internal_notes: str | None = None
    payment_method: PaymentMethod = PaymentMethod.CASH

class OrderCreate(OrderBase):
    items: list[OrderItemCreate]
    idempotency_key: str | None = None
    address_id: int | None = None
    customer_address: str | None = None
    delivery_person_id: int | None = None
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    offer_code: str | None = None
    manual_discount_type: DiscountType | None = None
    manual_discount_value: Decimal | None = Field(default=None, gt=0)
    discount_reason: str | None = None
    order_number: str | None = None
    order_date: date | None = None
    
    @field_validator('customer_id', 'address_id', 'delivery_person_id', mode='before')
    @classmethod
    def convert_zero_to_none(cls, v):
        if v == 0:
            return None
        return v

    @model_validator(mode='after')
    def validate_discount_rules(self):
        if (self.manual_discount_type is None) != (self.manual_discount_value is None):
            raise ValueError("Manual discount type and value must be provided together")
        if self.manual_discount_type == DiscountType.PERCENTAGE and self.manual_discount_value > Decimal(100):
            raise ValueError("Manual percentage discount cannot exceed 100%")
        if self.offer_code and self.manual_discount_type:
            raise ValueError("An offer and a manual discount cannot be combined")
        return self

class OrderUpdate(BaseModel):
    order_status: OrderStatus | None = None
    delivery_person_id: int | None = None
    internal_notes: str | None = None

    @field_validator('delivery_person_id', mode='before')
    @classmethod
    def convert_zero_to_none(cls, v):
        if v == 0:
            return None
        return v

class OrderUpdateFull(BaseModel):
    """Comprehensive order update schema for patch endpoint."""
    order_type: OrderType | None = None
    delivery_person_id: int | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_notes: str | None = None
    internal_notes: str | None = None
    address_id: int | None = None
    customer_address: str | None = None
    customer_id: int | None = None
    delivery_fee: Decimal | None = None
    items: list[OrderItemCreate] | None = None
    manual_discount_type: DiscountType | None = None
    manual_discount_value: Decimal | None = Field(default=None, gt=0)
    discount_reason: str | None = None
    payment_method: PaymentMethod | None = None

    @field_validator('delivery_person_id', 'address_id', mode='before')
    @classmethod
    def convert_zero_to_none(cls, v):
        if v == 0:
            return None
        return v

    @model_validator(mode='after')
    def validate_percentage_discount(self):
        if self.manual_discount_type == DiscountType.PERCENTAGE and self.manual_discount_value is not None and self.manual_discount_value > Decimal(100):
            raise ValueError("Manual percentage discount cannot exceed 100%")
        return self

class OrderResponse(OrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_number: str
    order_date: date
    created_at: datetime
    updated_at: datetime | None = None
    order_status: OrderStatus
    subtotal: Decimal
    discount_amount: Decimal
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = None
    discount_reason: str | None = None
    applied_offer: AppliedOfferResponse | None = None
    delivery_fee: Decimal
    total_amount: Decimal
    items: list[OrderItemResponse]
    creator_name: str | None = None
    delivery_person_name: str | None = None
    delivery_person_id: int | None = None
    address_id: int | None = None
    customer_address: str | None = None
    address: CustomerAddressResponse | None = None
    modifications: list["OrderModificationResponse"] = []

    @model_validator(mode='after')
    def validate_financial_integrity(self):
        if self.discount_amount < Decimal("0.00"):
            raise ValueError("Discount cannot be negative")
        if self.discount_amount > self.subtotal:
            raise ValueError("Discount cannot exceed subtotal")
        if self.total_amount < Decimal("0.00"):
            raise ValueError("Total cannot be negative")
        return self


class OrderModificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    changed_by_user_id: int | None = None
    changed_at: datetime
    changes: list[str]  # We will store a list of string messages

# Resolve forward reference for OrderResponse.modifications
OrderResponse.model_rebuild()

class OrderDetailResponse(OrderResponse):
    created_by_user_id: int | None = None
    delivery_person_id: int | None = None
    updated_at: datetime
    internal_notes: str | None = None
    modifications: list[OrderModificationResponse] = []


class OrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    orders: list[OrderResponse]


class DashboardOrderResponse(BaseModel):
    """Lean order shape used by the operational dashboard."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    order_number: str
    customer_name: str | None = None
    order_type: OrderType
    order_status: OrderStatus
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime | None = None
    items: list[OrderItemResponse]


class DashboardOrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    orders: list[DashboardOrderResponse]
