from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.customer.schemas import CustomerAddressResponse
from app.modules.orders.schemas import OrderResponse


class CustomerAccountAvailability(BaseModel):
    available: bool

class CustomerChallengeRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    purpose: Literal["activate", "reset_pin"]

class CustomerChallengeResponse(BaseModel):
    challenge_id: str
    whatsapp_url: str
    expires_in: int

class CustomerChallengeStatus(BaseModel):
    verified: bool

class CustomerLoginRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    pin: str = Field(pattern=r"^\d{4,12}$")
    device_name: str = Field(default="جهاز", max_length=120)

class CustomerCompleteRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    challenge_id: str = Field(min_length=20, max_length=200)
    purpose: Literal["activate", "reset_pin"]
    pin: str = Field(pattern=r"^\d{4,12}$")
    name: str | None = Field(default=None, min_length=2, max_length=100)
    device_name: str = Field(default="جهاز", max_length=120)

class CustomerTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    customer_id: int

class CustomerProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)

class CustomerProfile(BaseModel):
    id: int
    name: str
    phone_number: str
    whatsapp_status: str = "unknown"
    addresses: list[CustomerAddressResponse]

class CustomerDeviceResponse(BaseModel):
    id: str
    device_name: str
    last_used_at: datetime
    expires_at: datetime
    current: bool = False

class CustomerOrdersResponse(BaseModel):
    orders: list[OrderResponse]
