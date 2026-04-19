from pydantic import BaseModel
from typing import Optional

class SettingBase(BaseModel):
    key: str
    value_bool: bool
    description: Optional[str] = None

class SettingUpdate(BaseModel):
    value_bool: bool

class SettingResponse(SettingBase):
    class Config:
        from_attributes = True
