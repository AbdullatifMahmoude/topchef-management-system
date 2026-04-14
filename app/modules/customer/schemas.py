from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import List, Optional

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
    name: Optional[str] = None
    phone_number: Optional[str] = None

class CustomerResponse(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    addresses: List[CustomerAddressResponse] = []
