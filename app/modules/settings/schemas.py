
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettingBase(BaseModel):
    key: str
    value_bool: bool
    description: str | None = None

class SettingUpdate(BaseModel):
    value_bool: bool

class SettingResponse(SettingBase):
    model_config = ConfigDict(from_attributes=True)

class WhatsAppSettingsUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=2000)
    phone_number_id: str = Field(default="", max_length=100)
    first_order_template_name: str = Field(default="topchef_first_order_details", max_length=512)
    order_details_template_name: str = Field(default="topchef_order_details", max_length=512)
    order_status_template_name: str = Field(default="topchef_order_status", max_length=512)
    language_code: str = Field(default="ar", max_length=20)
    graph_api_version: str = Field(default="v23.0", pattern=r"^v\d+\.\d+$")
    enabled: bool = True
    bulk_template_name: str = Field(default="topchef_bulk_message", max_length=512)
    password_reset_template_name: str = Field(default="topchef_password_reset", max_length=512)
    reset_code_expiry_minutes: int = Field(default=10, ge=5, le=60)
    bulk_send_limit: int = Field(default=500, ge=1, le=5000)
    bulk_message: str = Field(default="", max_length=5000)
    business_phone_number: str = Field(default="201129820007", max_length=20)
    customer_service_phone: str = Field(default="", max_length=20)
    menu_url: str = Field(default="https://topchefeg.com/", max_length=500)
    webhook_verify_token: str | None = Field(default=None, max_length=512)
    app_secret: str | None = Field(default=None, max_length=512)

class WhatsAppSettingsResponse(BaseModel):
    api_key_configured: bool
    phone_number_id: str
    first_order_template_name: str
    order_details_template_name: str
    order_status_template_name: str
    language_code: str
    graph_api_version: str
    enabled: bool
    bulk_template_name: str
    password_reset_template_name: str
    reset_code_expiry_minutes: int
    bulk_send_limit: int
    bulk_message: str
    business_phone_number: str
    customer_service_phone: str = ""
    menu_url: str = "https://topchefeg.com/"
    webhook_verify_token_configured: bool
    app_secret_configured: bool

class BulkSendResponse(BaseModel):
    queued_count: int
    message: str


class PaymentSettingsUpdate(BaseModel):
    instapay_enabled: bool = False
    instapay_account: str = Field(default="", max_length=120)
    wallet_enabled: bool = False
    wallet_number: str = Field(default="", max_length=20)
    payment_account_name: str = Field(default="", max_length=100)


class PaymentSettingsResponse(PaymentSettingsUpdate):
    pass


class MenuCheckoutSettings(PaymentSettingsResponse):
    ordering_enabled: bool
    ordering_reason: str
    ordering_message: str
    whatsapp_business_phone: str = ""


class LoyaltyTier(BaseModel):
    from_amount: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    step_amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    points_per_step: int = Field(ge=1, le=100000)


class LoyaltyRedemptionRule(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    reward_type: Literal["fixed_discount", "free_product"] = "fixed_discount"
    points_required: int = Field(ge=1, le=1000000)
    discount_amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    product_id: int | None = Field(default=None, ge=1)
    variant_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_reward(self):
        if self.reward_type == "fixed_discount":
            if self.discount_amount is None or self.product_id is not None or self.variant_id is not None:
                raise ValueError("الخصم الثابت يحتاج قيمة خصم فقط")
        elif self.discount_amount is not None or not self.product_id or not self.variant_id:
            raise ValueError("الصنف المجاني يحتاج اختيار الصنف والحجم فقط")
        return self


class LoyaltySettingsUpdate(BaseModel):
    enabled: bool = False
    minimum_order_amount: Decimal = Field(default=Decimal(0), ge=0, max_digits=10, decimal_places=2)
    max_points_per_order: int = Field(default=10000, ge=1, le=1000000)
    tiers: list[LoyaltyTier] = Field(default_factory=list, max_length=20)
    redemption_enabled: bool = False
    redemption_rules: list[LoyaltyRedemptionRule] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_tiers(self):
        if self.enabled and not self.tiers:
            raise ValueError("أضف شريحة نقاط واحدة على الأقل قبل التفعيل")
        if self.tiers and self.tiers[0].from_amount != 0:
            raise ValueError("أول شريحة يجب أن تبدأ من صفر جنيه")
        for current, following in zip(self.tiers, self.tiers[1:]):
            width = following.from_amount - current.from_amount
            if width <= 0:
                raise ValueError("رتّب الشرائح تصاعديًا بدون تكرار حد البداية")
            if width % current.step_amount:
                raise ValueError("حد الشريحة التالية يجب أن يكمل خطوات الشريحة السابقة")
        if self.redemption_enabled and not self.redemption_rules:
            raise ValueError("أضف قاعدة استبدال واحدة على الأقل قبل التفعيل")
        ids = [rule.id for rule in self.redemption_rules]
        if len(ids) != len(set(ids)):
            raise ValueError("لا يمكن تكرار معرّف قاعدة الاستبدال")
        return self


class LoyaltySettingsResponse(LoyaltySettingsUpdate):
    configured: bool = False
    active: bool = False
    redemption_active: bool = False
