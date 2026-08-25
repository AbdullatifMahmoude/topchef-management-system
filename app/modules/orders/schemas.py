from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator, AliasChoices
from decimal import Decimal
from app.core.enums import OrderType, OrderSource, OrderStatus, DiscountType, PaymentMethod
from app.modules.customer.schemas import CustomerAddressResponse

class OrderItemBase(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemResponse(OrderItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    total_price: Decimal
    product_name: Optional[str] = None

class AppliedOfferResponse(BaseModel):
    code: str
    display_name: Optional[str] = None
    discount_type: DiscountType
    discount_value: Decimal
    discount_amount: Decimal

class OrderBase(BaseModel):
    customer_id: Optional[int] = None
    customer_phone: Optional[str] = None
    customer_name: Optional[str] = None
    order_type: OrderType
    source: OrderSource = Field(OrderSource.ONLINE, validation_alias=AliasChoices("source", "order_source"))
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None
    payment_method: PaymentMethod = PaymentMethod.CASH

class OrderCreate(OrderBase):
    items: List[OrderItemCreate]
    idempotency_key: Optional[str] = None
    address_id: Optional[int] = None
    customer_address: Optional[str] = None
    delivery_person_id: Optional[int] = None
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    offer_code: Optional[str] = None
    manual_discount_type: Optional[DiscountType] = None
    manual_discount_value: Optional[Decimal] = None
    discount_reason: Optional[str] = None
    order_number: Optional[str] = None
    order_date: Optional[date] = None
    
    @field_validator('customer_id', 'address_id', 'delivery_person_id', mode='before')
    @classmethod
    def convert_zero_to_none(cls, v):
        if v == 0:
            return None
        return v

class OrderUpdate(BaseModel):
    order_status: Optional[OrderStatus] = None
    delivery_person_id: Optional[int] = None
    internal_notes: Optional[str] = None

    @field_validator('delivery_person_id', mode='before')
    @classmethod
    def convert_zero_to_none(cls, v):
        if v == 0:
            return None
        return v

class OrderUpdateFull(BaseModel):
    """Comprehensive order update schema for patch endpoint."""
    order_type: Optional[OrderType] = None
    delivery_person_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None
    address_id: Optional[int] = None
    customer_address: Optional[str] = None
    customer_id: Optional[int] = None
    delivery_fee: Optional[Decimal] = None
    items: Optional[List[OrderItemCreate]] = None
    manual_discount_type: Optional[DiscountType] = None
    manual_discount_value: Optional[Decimal] = None
    discount_reason: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None

    @field_validator('delivery_person_id', 'address_id', mode='before')
    @classmethod
    def convert_zero_to_none(cls, v):
        if v == 0:
            return None
        return v

class OrderResponse(OrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_number: str
    order_date: date
    created_at: datetime
    updated_at: Optional[datetime] = None
    order_status: OrderStatus
    subtotal: Decimal
    discount_amount: Decimal
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[Decimal] = None
    discount_reason: Optional[str] = None
    applied_offer: Optional[AppliedOfferResponse] = None
    delivery_fee: Decimal
    total_amount: Decimal
    items: List[OrderItemResponse]
    creator_name: Optional[str] = None
    delivery_person_name: Optional[str] = None
    delivery_person_id: Optional[int] = None
    address_id: Optional[int] = None
    customer_address: Optional[str] = None
    address: Optional[CustomerAddressResponse] = None
    modifications: List["OrderModificationResponse"] = []

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
    changed_by_user_id: Optional[int] = None
    changed_at: datetime
    changes: List[str]  # We will store a list of string messages

# Resolve forward reference for OrderResponse.modifications
OrderResponse.model_rebuild()

class OrderDetailResponse(OrderResponse):
    created_by_user_id: Optional[int] = None
    delivery_person_id: Optional[int] = None
    updated_at: datetime
    internal_notes: Optional[str] = None
    modifications: List[OrderModificationResponse] = []


class OrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    orders: List[OrderResponse]
