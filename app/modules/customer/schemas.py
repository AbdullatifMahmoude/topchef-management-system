from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CustomerAddressBase(BaseModel):
    address: str

class CustomerAddressCreate(CustomerAddressBase):
    pass

class CustomerAddressResponse(CustomerAddressBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    created_at: datetime

class CustomerBase(BaseModel):
    name: str
    phone_number: str

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(BaseModel):
    name: str | None = None
    phone_number: str | None = None

class CustomerResponse(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    whatsapp_status: str = "unknown"
    whatsapp_consent_at: datetime | None = None
    whatsapp_checked_at: datetime | None = None
    whatsapp_failure_reason: str | None = None
    addresses: list[CustomerAddressResponse] = []
