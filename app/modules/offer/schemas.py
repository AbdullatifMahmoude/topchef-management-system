from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import DiscountType


class OfferBase(BaseModel):
    code: str = Field(..., max_length=255)
    display_name: str | None = Field(None, max_length=255)
    discount_type: DiscountType
    discount_value: Decimal = Field(..., gt=0)
    min_order_amount: Decimal | None = Field(None, ge=0)
    min_quantity: int | None = Field(None, gt=0)
    max_quantity: int | None = Field(None, gt=0)
    max_discount_amount: Decimal | None = Field(None, gt=0)
    usage_limit: int | None = Field(None, gt=0)
    usage_per_user: int | None = Field(None, gt=0)
    is_active: bool = True
    valid_from: datetime = Field(default_factory=datetime.utcnow)
    valid_to: datetime
    product_ids: list[int] = Field(default_factory=list)
    rules: dict[str, Any] = Field(default_factory=dict)

    @field_validator("valid_from", "valid_to", mode="after")
    @classmethod
    def use_normal_calendar_time(cls, value: datetime) -> datetime:
        # Offers use normal midnight-to-midnight calendar time, not the business-day
        # restaurant business-day cutoff. Store the Cairo wall clock as naive.
        if value.tzinfo is not None:
            value = value.astimezone(timezone(timedelta(hours=3)))
        return value.replace(tzinfo=None)

class OfferCreate(OfferBase):
    pass

class OfferUpdate(BaseModel):
    code: str | None = Field(None, max_length=255)
    display_name: str | None = Field(None, max_length=255)
    discount_type: DiscountType | None = None
    discount_value: Decimal | None = Field(None, gt=0)
    min_order_amount: Decimal | None = Field(None, ge=0)
    min_quantity: int | None = Field(None, gt=0)
    max_quantity: int | None = Field(None, gt=0)
    max_discount_amount: Decimal | None = Field(None, gt=0)
    usage_limit: int | None = Field(None, gt=0)
    usage_per_user: int | None = Field(None, gt=0)
    is_active: bool | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    product_ids: list[int] | None = None
    rules: dict[str, Any] | None = None

    @field_validator("valid_from", "valid_to", mode="after")
    @classmethod
    def use_normal_calendar_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone(timedelta(hours=3)))
        return value.replace(tzinfo=None) if value is not None else None

class OfferResponse(OfferBase):
    offer_id: int
    current_usage: int = 0

    model_config = ConfigDict(from_attributes=True)

class ApplyOfferResponse(BaseModel):
    items: list # List of items for context
    subtotal: Decimal
    discount_amount: Decimal
    total_after_discount: Decimal
    offer_metadata: OfferResponse | None = None
    applied_successfully: bool = False
    message: str | None = None
    waive_delivery_fee: bool = False

class OfferUsageActivity(BaseModel):
    offer_name: str
    offer_code: str
    customer_phone: str | None = None
    cashier_name: str | None = None
    order_id: int | None = None
    discount_amount: Decimal
    applied_at: datetime

class OfferAnalyticsResponse(BaseModel):
    active_now: int = 0
    scheduled: int = 0
    stopped_or_ended: int = 0
    redemptions_today: int = 0
    discounts_today: Decimal = Decimal("0.00")
    recent_activity: list[OfferUsageActivity] = Field(default_factory=list)
