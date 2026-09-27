import contextlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.logging import logger
from app.core.secrets import decrypt_secret, encrypt_secret
from app.modules.menu.models import Product
from app.modules.settings import schemas
from app.modules.settings.repository import SettingsRepository

DEFAULT_TRANSFER_NUMBER = "01009515031"


class SettingsService:
    WHATSAPP_API_KEY = "whatsapp_api_key"
    WHATSAPP_PHONE_NUMBER_ID = "whatsapp_phone_number_id"
    WHATSAPP_FIRST_ORDER_TEMPLATE_NAME = "whatsapp_first_order_template_name"
    WHATSAPP_TEMPLATE_NAME = "whatsapp_template_name"
    WHATSAPP_ORDER_DETAILS_TEMPLATE_NAME = "whatsapp_order_details_template_name"
    WHATSAPP_ORDER_STATUS_TEMPLATE_NAME = "whatsapp_order_status_template_name"
    WHATSAPP_LANGUAGE_CODE = "whatsapp_language_code"
    WHATSAPP_GRAPH_API_VERSION = "whatsapp_graph_api_version"
    WHATSAPP_ENABLED = "whatsapp_enabled"
    WHATSAPP_BULK_TEMPLATE_NAME = "whatsapp_bulk_template_name"
    WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME = "whatsapp_password_reset_template_name"
    WHATSAPP_RESET_EXPIRY_MINUTES = "whatsapp_reset_expiry_minutes"
    WHATSAPP_BULK_SEND_LIMIT = "whatsapp_bulk_send_limit"
    WHATSAPP_BULK_MESSAGE = "whatsapp_bulk_message"
    WHATSAPP_BUSINESS_PHONE = "whatsapp_business_phone"
    WHATSAPP_CUSTOMER_SERVICE_PHONE = "whatsapp_customer_service_phone"
    WHATSAPP_MENU_URL = "whatsapp_menu_url"
    WHATSAPP_WEBHOOK_VERIFY_TOKEN = "whatsapp_webhook_verify_token"
    WHATSAPP_APP_SECRET = "whatsapp_app_secret"
    INSTAPAY_ENABLED = "instapay_enabled"
    INSTAPAY_ACCOUNT = "instapay_account"
    WALLET_ENABLED = "wallet_enabled"
    WALLET_NUMBER = "wallet_number"
    PAYMENT_ACCOUNT_NAME = "payment_account_name"
    LOYALTY_RULES = "loyalty_rules"
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis
        self.repo = SettingsRepository(db)

    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield

    async def get_web_orders_status(self) -> bool:
        """Check if web orders are enabled, with Redis fallback."""
        cache_key = "settings:web_orders_enabled"
        
        # 1. Try Cache
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached is not None:
                    return cached.lower() == "true"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Settings cache read failed for %s: %s", cache_key, exc)

        # 2. Get DB
        setting = await self.repo.get_setting("web_orders_enabled")
        status = setting.value_bool if setting else True # Default to True
        
        # 3. Update Cache
        if self.redis:
            try:
                await self.redis.setex(cache_key, 3600, str(status).lower())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Settings cache write failed for %s: %s", cache_key, exc)
        
        return status

    async def toggle_web_orders(self, enabled: bool):
        async with self._transaction_scope():
            setting = await self.repo.create_or_update_setting(
                key="web_orders_enabled",
                value_bool=enabled,
                description="Toggle receiving online orders from web menu"
            )
            
            # 4. Emit WebSocket Event for real-time UI
            from app.core.events import order_events_manager
            
            await order_events_manager.emit({
                "type": "SETTING_UPDATED",
                "data": {
                    "key": "web_orders_enabled",
                    "value_bool": enabled
                }
            })

            # Invalidate Cache
            if self.redis:
                try:
                    await self.redis.setex("settings:web_orders_enabled", 3600, str(enabled).lower())
                    await self.redis.delete("settings:menu_checkout")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Web-order settings cache update failed: %s", exc)
            
            logger.info(f"Web orders status toggled to: {enabled}")
            return setting

    async def get_payment_settings(self) -> schemas.PaymentSettingsResponse:
        keys = (self.INSTAPAY_ENABLED, self.INSTAPAY_ACCOUNT, self.WALLET_ENABLED,
                self.WALLET_NUMBER, self.PAYMENT_ACCOUNT_NAME)
        values = await self.repo.get_settings(keys)
        text = lambda key: (values.get(key).value_text or "") if values.get(key) else ""
        flag = lambda key: bool(values.get(key) and values.get(key).value_bool)
        return schemas.PaymentSettingsResponse(
            instapay_enabled=flag(self.INSTAPAY_ENABLED),
            instapay_account=text(self.INSTAPAY_ACCOUNT).strip() or DEFAULT_TRANSFER_NUMBER,
            wallet_enabled=flag(self.WALLET_ENABLED),
            wallet_number=text(self.WALLET_NUMBER).strip() or DEFAULT_TRANSFER_NUMBER,
            payment_account_name=text(self.PAYMENT_ACCOUNT_NAME),
        )

    async def get_loyalty_settings(self) -> schemas.LoyaltySettingsResponse:
        row = await self.repo.get_setting(self.LOYALTY_RULES)
        if not row or not row.value_text:
            return schemas.LoyaltySettingsResponse()
        try:
            data = schemas.LoyaltySettingsUpdate.model_validate(json.loads(row.value_text))
        except (ValueError, TypeError) as exc:
            logger.error("Invalid loyalty rules stored in app_settings: %s", type(exc).__name__)
            return schemas.LoyaltySettingsResponse()
        return schemas.LoyaltySettingsResponse(
            **data.model_dump(), configured=bool(data.tiers), active=data.enabled and bool(data.tiers),
            redemption_active=data.redemption_enabled and bool(data.redemption_rules),
        )

    async def update_loyalty_settings(self, data: schemas.LoyaltySettingsUpdate) -> schemas.LoyaltySettingsResponse:
        async with self._transaction_scope():
            for rule in data.redemption_rules:
                if rule.reward_type != "free_product":
                    continue
                product = await self.db.scalar(select(Product).where(Product.id == rule.product_id).options(
                    selectinload(Product.variants), selectinload(Product.category),
                ))
                if not product or product.is_deleted or not product.is_available or not product.category \
                        or not product.category.is_active or product.category.is_deleted \
                        or not any(variant.id == rule.variant_id and not variant.is_deleted and variant.price > 0
                                   for variant in product.variants):
                    raise ValidationError("اختر صنفًا وحجمًا متاحين لقاعدة الصنف المجاني")
            await self.repo.create_or_update_text_setting(
                self.LOYALTY_RULES, data.model_dump_json(), "Customer loyalty earning rules",
            )
            await self.db.flush()
        return await self.get_loyalty_settings()

    async def update_payment_settings(self, data: schemas.PaymentSettingsUpdate) -> schemas.PaymentSettingsResponse:
        async with self._transaction_scope():
            for key, enabled in ((self.INSTAPAY_ENABLED, data.instapay_enabled),
                                 (self.WALLET_ENABLED, data.wallet_enabled)):
                await self.repo.create_or_update_setting(key, enabled, "Enable menu payment method")
            for key, value in ((self.INSTAPAY_ACCOUNT, data.instapay_account),
                               (self.WALLET_NUMBER, data.wallet_number),
                               (self.PAYMENT_ACCOUNT_NAME, data.payment_account_name)):
                await self.repo.create_or_update_text_setting(key, value.strip(), "Public transfer details")
            await self.db.flush()
        if self.redis:
            try:
                await self.redis.delete("settings:menu_checkout")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Menu-checkout cache invalidation failed: %s", exc)
        return await self.get_payment_settings()

    async def get_menu_checkout_settings(self) -> schemas.MenuCheckoutSettings:
        from sqlalchemy import func, select

        from app.core.business_calendar import (
            get_current_business_date,
            is_weekly_holiday,
        )
        from app.modules.shifts.models import CashierShift
        if self.redis:
            try:
                cached = await self.redis.get("settings:menu_checkout")
                if cached:
                    return schemas.MenuCheckoutSettings.model_validate_json(cached)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Menu-checkout cache read failed: %s", exc)
        payment = await self.get_payment_settings()
        if is_weekly_holiday():
            enabled, reason, message = False, "weekly_holiday", "النهارده إجازتنا الأسبوعية. مستنيينك بكرة بإذن الله."
        else:
            active = await self.db.scalar(select(func.count(CashierShift.id)).where(
                CashierShift.target_date == get_current_business_date(), CashierShift.end_time.is_(None))) or 0
            manually_enabled = await self.get_web_orders_status()
            if not active:
                enabled, reason, message = False, "closed", "المطعم مش شغال دلوقتي. الطلب هيفتح مع بداية الشيفت."
            elif not manually_enabled:
                enabled, reason, message = False, "busy", "عندنا ضغط طلبات دلوقتي. جرّب تطلب كمان ربع ساعة."
            else:
                enabled, reason, message = True, "open", "الطلبات متاحة"
        whatsapp = await self.get_whatsapp_settings()
        result = schemas.MenuCheckoutSettings(
            **payment.model_dump(), ordering_enabled=enabled,
            ordering_reason=reason, ordering_message=message,
            whatsapp_business_phone=whatsapp.business_phone_number,
        )
        if self.redis:
            try:
                await self.redis.setex("settings:menu_checkout", 30, result.model_dump_json())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Menu-checkout cache write failed: %s", exc)
        return result

    async def get_whatsapp_settings(self) -> schemas.WhatsAppSettingsResponse:
        keys = (
            self.WHATSAPP_API_KEY, self.WHATSAPP_PHONE_NUMBER_ID,
            self.WHATSAPP_FIRST_ORDER_TEMPLATE_NAME,
            self.WHATSAPP_TEMPLATE_NAME, self.WHATSAPP_ORDER_DETAILS_TEMPLATE_NAME,
            self.WHATSAPP_ORDER_STATUS_TEMPLATE_NAME, self.WHATSAPP_LANGUAGE_CODE,
            self.WHATSAPP_GRAPH_API_VERSION, self.WHATSAPP_ENABLED,
            self.WHATSAPP_BULK_TEMPLATE_NAME, self.WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME,
            self.WHATSAPP_RESET_EXPIRY_MINUTES, self.WHATSAPP_BULK_SEND_LIMIT,
            self.WHATSAPP_BULK_MESSAGE,
            self.WHATSAPP_BUSINESS_PHONE, self.WHATSAPP_WEBHOOK_VERIFY_TOKEN,
            self.WHATSAPP_APP_SECRET, self.WHATSAPP_CUSTOMER_SERVICE_PHONE,
            self.WHATSAPP_MENU_URL,
        )
        values = await self.repo.get_settings(keys)
        text = lambda key, default="": (
            values[key].value_text if values.get(key) and values[key].value_text is not None else default
        )
        return schemas.WhatsAppSettingsResponse(
            api_key_configured=bool(decrypt_secret(text(self.WHATSAPP_API_KEY))),
            phone_number_id=text(self.WHATSAPP_PHONE_NUMBER_ID),
            first_order_template_name=text(
                self.WHATSAPP_FIRST_ORDER_TEMPLATE_NAME, "topchef_first_order_details"
            ),
            order_details_template_name=text(
                self.WHATSAPP_ORDER_DETAILS_TEMPLATE_NAME,
                text(self.WHATSAPP_TEMPLATE_NAME, "topchef_order_details"),
            ),
            order_status_template_name=text(
                self.WHATSAPP_ORDER_STATUS_TEMPLATE_NAME, "topchef_order_status"
            ),
            language_code=text(self.WHATSAPP_LANGUAGE_CODE, "ar"),
            graph_api_version=text(self.WHATSAPP_GRAPH_API_VERSION, "v23.0"),
            enabled=not settings.WHATSAPP_INTEGRATION_PAUSED and text(self.WHATSAPP_ENABLED, "true").lower() == "true",
            bulk_template_name=text(self.WHATSAPP_BULK_TEMPLATE_NAME, "topchef_bulk_message"),
            password_reset_template_name=text(self.WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME, "topchef_password_reset"),
            reset_code_expiry_minutes=int(text(self.WHATSAPP_RESET_EXPIRY_MINUTES, "10")),
            bulk_send_limit=int(text(self.WHATSAPP_BULK_SEND_LIMIT, "500")),
            bulk_message=text(self.WHATSAPP_BULK_MESSAGE),
            business_phone_number=text(self.WHATSAPP_BUSINESS_PHONE, "201129820007"),
            customer_service_phone=text(self.WHATSAPP_CUSTOMER_SERVICE_PHONE),
            menu_url=text(self.WHATSAPP_MENU_URL, "https://topchefeg.com/"),
            webhook_verify_token_configured=bool(decrypt_secret(text(self.WHATSAPP_WEBHOOK_VERIFY_TOKEN))),
            app_secret_configured=bool(decrypt_secret(text(self.WHATSAPP_APP_SECRET))),
        )

    async def update_whatsapp_settings(
        self, data: schemas.WhatsAppSettingsUpdate
    ) -> schemas.WhatsAppSettingsResponse:
        async with self._transaction_scope():
            # A blank key means "keep the currently saved key" so it is never
            # necessary to send the secret back to the browser.
            if data.api_key is not None and data.api_key.strip():
                await self.repo.create_or_update_text_setting(
                    self.WHATSAPP_API_KEY,
                    encrypt_secret(data.api_key.strip()),
                    "WhatsApp provider API key",
                )
            for secret_value, key, description in (
                (data.webhook_verify_token, self.WHATSAPP_WEBHOOK_VERIFY_TOKEN, "Meta webhook verification token"),
                (data.app_secret, self.WHATSAPP_APP_SECRET, "Meta app secret"),
            ):
                if secret_value is not None and secret_value.strip():
                    await self.repo.create_or_update_text_setting(
                        key, encrypt_secret(secret_value.strip()), description,
                    )
            text_settings = {
                self.WHATSAPP_PHONE_NUMBER_ID: (data.phone_number_id.strip(), "Meta WhatsApp phone number ID"),
                self.WHATSAPP_FIRST_ORDER_TEMPLATE_NAME: (
                    data.first_order_template_name.strip(), "Approved first-order WhatsApp utility template"
                ),
                self.WHATSAPP_ORDER_DETAILS_TEMPLATE_NAME: (
                    data.order_details_template_name.strip(), "Approved WhatsApp order details utility template"
                ),
                self.WHATSAPP_ORDER_STATUS_TEMPLATE_NAME: (
                    data.order_status_template_name.strip(), "Approved WhatsApp order status utility template"
                ),
                self.WHATSAPP_LANGUAGE_CODE: (data.language_code.strip(), "WhatsApp template language"),
                self.WHATSAPP_GRAPH_API_VERSION: (data.graph_api_version.strip(), "Meta Graph API version"),
                self.WHATSAPP_ENABLED: (str(data.enabled).lower(), "Enable automatic WhatsApp notifications"),
                self.WHATSAPP_BULK_TEMPLATE_NAME: (data.bulk_template_name.strip(), "Approved bulk message template"),
                self.WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME: (data.password_reset_template_name.strip(), "Approved password reset template"),
                self.WHATSAPP_RESET_EXPIRY_MINUTES: (str(data.reset_code_expiry_minutes), "Password reset code lifetime"),
                self.WHATSAPP_BULK_SEND_LIMIT: (str(data.bulk_send_limit), "Maximum bulk recipients per send"),
                self.WHATSAPP_BUSINESS_PHONE: (data.business_phone_number.strip(), "Public WhatsApp business number"),
                self.WHATSAPP_CUSTOMER_SERVICE_PHONE: (data.customer_service_phone.strip(), "Human customer service WhatsApp number"),
                self.WHATSAPP_MENU_URL: (data.menu_url.strip(), "Public ordering menu URL"),
            }
            for key, (value, description) in text_settings.items():
                await self.repo.create_or_update_text_setting(key, value, description)
            await self.repo.create_or_update_text_setting(
                self.WHATSAPP_BULK_MESSAGE,
                data.bulk_message.strip(),
                "Default WhatsApp bulk message",
            )
            await self.db.flush()

        logger.info("WhatsApp settings updated")
        return await self.get_whatsapp_settings()

    async def get_whatsapp_access_token(self) -> str:
        row = await self.repo.get_setting(self.WHATSAPP_API_KEY)
        return decrypt_secret(row.value_text if row and row.value_text else "")

    async def get_whatsapp_webhook_verify_token(self) -> str:
        row = await self.repo.get_setting(self.WHATSAPP_WEBHOOK_VERIFY_TOKEN)
        return decrypt_secret(row.value_text if row and row.value_text else "")

    async def get_whatsapp_app_secret(self) -> str:
        row = await self.repo.get_setting(self.WHATSAPP_APP_SECRET)
        return decrypt_secret(row.value_text if row and row.value_text else "")
