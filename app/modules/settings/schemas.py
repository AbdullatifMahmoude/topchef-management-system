from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

class SettingBase(BaseModel):
    key: str
    value_bool: bool
    description: Optional[str] = None

class SettingUpdate(BaseModel):
    value_bool: bool

class SettingResponse(SettingBase):
    model_config = ConfigDict(from_attributes=True)

class WhatsAppSettingsUpdate(BaseModel):
    api_key: Optional[str] = Field(default=None, max_length=2000)
    phone_number_id: str = Field(default="", max_length=100)
    template_name: str = Field(default="topchef_order_update", max_length=512)
    language_code: str = Field(default="ar", max_length=20)
    graph_api_version: str = Field(default="v23.0", pattern=r"^v\d+\.\d+$")
    enabled: bool = True
    bulk_template_name: str = Field(default="topchef_bulk_message", max_length=512)
    password_reset_template_name: str = Field(default="topchef_password_reset", max_length=512)
    reset_code_expiry_minutes: int = Field(default=10, ge=5, le=60)
    bulk_send_limit: int = Field(default=500, ge=1, le=5000)
    bulk_message: str = Field(default="", max_length=5000)

class WhatsAppSettingsResponse(BaseModel):
    api_key_configured: bool
    phone_number_id: str
    template_name: str
    language_code: str
    graph_api_version: str
    enabled: bool
    bulk_template_name: str
    password_reset_template_name: str
    reset_code_expiry_minutes: int
    bulk_send_limit: int
    bulk_message: str

class BulkSendResponse(BaseModel):
    queued_count: int
    message: str
