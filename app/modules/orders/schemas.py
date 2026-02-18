from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal


class OrderItemBase(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(max_digits=10, decimal_places=2)


class OrderItemCreate(OrderItemBase):
    pass


class OrderItemResponse(OrderItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total_price: Decimal = Field(max_digits=10, decimal_places=2)


class OrderBase(BaseModel):
    customer_id: int
    order_type: str
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None


class OrderCreate(OrderBase):
    items: List[OrderItemCreate]
    idempotency_key: Optional[str] = None
    address_id: Optional[int] = None
    delivery_person_id: Optional[int] = None


class OrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    order_type: Optional[str]  = None
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None
    order_status: Optional[str] = None
    delivery_person_id: Optional[int] = None


class OrderResponse(OrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_number: str
    order_date: date
    order_status: str
    order_type: str
    order_source: str
    subtotal: Decimal = Field(max_digits=10, decimal_places=2)
    discount_amount: Decimal = Field(max_digits=10, decimal_places=2)
    total_amount: Decimal = Field(max_digits=10, decimal_places=2)
    delivery_person_name: Optional[str] = None
    items: List[OrderItemResponse]


class OrderDetailResponse(OrderResponse):
    created_by_user_id: Optional[int] = None
    created_by_user_name: Optional[str] = None
    delivery_person_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    internal_notes: Optional[str] = None


class OrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    orders: List[OrderResponse]
