from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Any, Dict
from decimal import Decimal
from app.core.enums import DiscountType

class OfferBase(BaseModel):
    code: str = Field(..., max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)
    discount_type: DiscountType
    discount_value: Decimal = Field(..., gt=0)
    min_order_amount: Optional[Decimal] = Field(None, ge=0)
    min_quantity: Optional[int] = Field(None, gt=0)
    max_quantity: Optional[int] = Field(None, gt=0)
    max_discount_amount: Optional[Decimal] = Field(None, gt=0)
    usage_limit: Optional[int] = Field(None, gt=0)
    usage_per_user: Optional[int] = Field(None, gt=0)
    is_active: bool = True
    valid_from: datetime = Field(default_factory=datetime.utcnow)
    valid_to: datetime
    product_ids: List[int] = Field(default_factory=list)
    rules: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("valid_from", "valid_to", mode="after")
    @classmethod
    def use_normal_calendar_time(cls, value: datetime) -> datetime:
        # Offers use normal midnight-to-midnight calendar time, not the 5am
        # restaurant business-day cutoff. Store the Cairo wall clock as naive.
        if value.tzinfo is not None:
            value = value.astimezone(timezone(timedelta(hours=3)))
        return value.replace(tzinfo=None)

class OfferCreate(OfferBase):
    pass

class OfferUpdate(BaseModel):
    code: Optional[str] = Field(None, max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[Decimal] = Field(None, gt=0)
    min_order_amount: Optional[Decimal] = Field(None, ge=0)
    min_quantity: Optional[int] = Field(None, gt=0)
    max_quantity: Optional[int] = Field(None, gt=0)
    max_discount_amount: Optional[Decimal] = Field(None, gt=0)
    usage_limit: Optional[int] = Field(None, gt=0)
    usage_per_user: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    product_ids: Optional[List[int]] = None
    rules: Optional[Dict[str, Any]] = None

    @field_validator("valid_from", "valid_to", mode="after")
    @classmethod
    def use_normal_calendar_time(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone(timedelta(hours=3)))
        return value.replace(tzinfo=None) if value is not None else None

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
    waive_delivery_fee: bool = False

class OfferUsageActivity(BaseModel):
    offer_name: str
    offer_code: str
    customer_phone: Optional[str] = None
    cashier_name: Optional[str] = None
    order_id: Optional[int] = None
    discount_amount: Decimal
    applied_at: datetime

class OfferAnalyticsResponse(BaseModel):
    active_now: int = 0
    scheduled: int = 0
    stopped_or_ended: int = 0
    redemptions_today: int = 0
    discounts_today: Decimal = Decimal("0.00")
    recent_activity: List[OfferUsageActivity] = Field(default_factory=list)
