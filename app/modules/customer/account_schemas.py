from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.customer.schemas import CustomerAddressResponse
from app.modules.orders.schemas import OrderResponse


class CustomerAccountAvailability(BaseModel):
    available: bool

class CustomerChallengeRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    phone: str | None = Field(default=None, min_length=10, max_length=12)
    purpose: Literal["activate", "reset_pin"]

    @model_validator(mode="after")
    def require_phone_for_activation(self):
        if self.purpose == "activate" and not self.phone:
            raise ValueError("رقم الهاتف مطلوب لتفعيل الحساب")
        return self

class CustomerChallengeResponse(BaseModel):
    challenge_id: str
    expires_in: int

class CustomerChallengeVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")

class CustomerChallengeStatus(BaseModel):
    verified: bool

class CustomerLoginRequest(BaseModel):
    identifier: str = Field(min_length=5, max_length=254)
    pin: str = Field(pattern=r"^\d{4,12}$")
    device_name: str = Field(default="جهاز", max_length=120)

class CustomerCompleteRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    phone: str | None = Field(default=None, min_length=10, max_length=12)
    challenge_id: str = Field(min_length=20, max_length=200)
    purpose: Literal["activate", "reset_pin"]
    pin: str = Field(pattern=r"^\d{4,12}$")
    pin_confirmation: str = Field(pattern=r"^\d{4,12}$")
    name: str | None = Field(default=None, min_length=2, max_length=100)
    device_name: str = Field(default="جهاز", max_length=120)

    @model_validator(mode="after")
    def validate_completion(self):
        if self.pin != self.pin_confirmation:
            raise ValueError("رقما PIN غير متطابقين")
        if self.purpose == "activate" and not self.phone:
            raise ValueError("رقم الهاتف مطلوب لتفعيل الحساب")
        return self

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
    email: str | None = None
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
