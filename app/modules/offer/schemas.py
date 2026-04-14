from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List
from decimal import Decimal
from app.core.enums import DiscountType

class OfferBase(BaseModel):
    code: str = Field(..., max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)
    discount_type: DiscountType
    discount_value: Decimal = Field(..., gt=0)
    min_order_amount: Optional[Decimal] = None
    min_quantity: Optional[int] = None
    max_quantity: Optional[int] = None
    max_discount_amount: Optional[Decimal] = None
    usage_limit: Optional[int] = None
    usage_per_user: Optional[int] = None
    is_active: bool = True
    valid_from: datetime = Field(default_factory=datetime.utcnow)
    valid_to: datetime

class OfferCreate(OfferBase):
    pass

class OfferUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[Decimal] = Field(None, gt=0)
    min_order_amount: Optional[Decimal] = None
    min_quantity: Optional[int] = None
    max_quantity: Optional[int] = None
    max_discount_amount: Optional[Decimal] = None
    usage_limit: Optional[int] = None
    usage_per_user: Optional[int] = None
    is_active: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

class OfferResponse(OfferBase):
    offer_id: int
    current_usage: int = 0

    model_config = ConfigDict(from_attributes=True)

class ApplyOfferResponse(BaseModel):
    items: List # List of items for context
    subtotal: Decimal
    discount_amount: Decimal
    total_after_discount: Decimal
    offer_metadata: Optional[OfferResponse] = None
    applied_successfully: bool = False
    message: Optional[str] = None
