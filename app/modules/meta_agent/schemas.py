from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


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


class OrderTrackingResponse(BaseModel):
    order_number: str
    status: str
    status_label: str
    updated_at: datetime
    history: list[OrderStatusEvent]


class AgentCapabilities(BaseModel):
    allowed: list[str]
    handoff_required: list[str]
    specialist_message: str = Field(
        default="هذا الطلب يحتاج إلى مختص من المطعم لإتمامه بأمان."
    )
