from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.business_calendar import order_time_in_cairo


class MenuVariant(BaseModel):
    id: int
    name: str
    price: Decimal


class MenuProduct(BaseModel):
    id: int
    name: str
    description: str | None = None
    category: str
    variants: list[MenuVariant]


class MenuResponse(BaseModel):
    currency: str = "EGP"
    products: list[MenuProduct]


class OrderStatusEvent(BaseModel):
    status: str
    status_label: str
    changed_at: datetime

    @field_validator("changed_at", mode="before")
    @classmethod
    def display_change_time(cls, value):
        return order_time_in_cairo(value) if isinstance(value, datetime) and value.tzinfo is None else value


class OrderTrackingResponse(BaseModel):
    order_number: str
    status: str
    status_label: str
    updated_at: datetime
    history: list[OrderStatusEvent]

    @field_validator("updated_at", mode="before")
    @classmethod
    def display_update_time(cls, value):
        return order_time_in_cairo(value) if isinstance(value, datetime) and value.tzinfo is None else value


class AgentCapabilities(BaseModel):
    allowed: list[str]
    handoff_required: list[str]
    specialist_message: str = Field(
        default="هذا الطلب يحتاج إلى مختص من المطعم لإتمامه بأمان."
    )


class CustomerVerificationRequest(BaseModel):
    customer_phone: str = Field(
        min_length=10,
        max_length=20,
        description="WhatsApp sender phone number from the current conversation",
    )
    message: str = Field(
        min_length=12,
        max_length=200,
        description="The customer's message containing the exact TCV-XXXXXXXX code",
    )


class CustomerVerificationResponse(BaseModel):
    verified: bool
