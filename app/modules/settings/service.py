import contextlib
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.settings.repository import SettingsRepository
from app.modules.settings import schemas
from app.core.logging import logger
from app.core.secrets import decrypt_secret, encrypt_secret

class SettingsService:
    WHATSAPP_API_KEY = "whatsapp_api_key"
    WHATSAPP_PHONE_NUMBER_ID = "whatsapp_phone_number_id"
    WHATSAPP_TEMPLATE_NAME = "whatsapp_template_name"
    WHATSAPP_LANGUAGE_CODE = "whatsapp_language_code"
    WHATSAPP_GRAPH_API_VERSION = "whatsapp_graph_api_version"
    WHATSAPP_ENABLED = "whatsapp_enabled"
    WHATSAPP_BULK_TEMPLATE_NAME = "whatsapp_bulk_template_name"
    WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME = "whatsapp_password_reset_template_name"
    WHATSAPP_RESET_EXPIRY_MINUTES = "whatsapp_reset_expiry_minutes"
    WHATSAPP_BULK_SEND_LIMIT = "whatsapp_bulk_send_limit"
    WHATSAPP_BULK_MESSAGE = "whatsapp_bulk_message"
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
            except Exception:
                pass

        # 2. Get DB
        setting = await self.repo.get_setting("web_orders_enabled")
        status = setting.value_bool if setting else True # Default to True
        
        # 3. Update Cache
        if self.redis:
            try:
                await self.redis.setex(cache_key, 3600, str(status).lower())
            except Exception:
                pass
        
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
                except Exception:
                    pass
            
            logger.info(f"Web orders status toggled to: {enabled}")
            return setting

    async def get_whatsapp_settings(self) -> schemas.WhatsAppSettingsResponse:
        keys = (
            self.WHATSAPP_API_KEY, self.WHATSAPP_PHONE_NUMBER_ID,
            self.WHATSAPP_TEMPLATE_NAME, self.WHATSAPP_LANGUAGE_CODE,
            self.WHATSAPP_GRAPH_API_VERSION, self.WHATSAPP_ENABLED,
            self.WHATSAPP_BULK_TEMPLATE_NAME, self.WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME,
            self.WHATSAPP_RESET_EXPIRY_MINUTES, self.WHATSAPP_BULK_SEND_LIMIT,
            self.WHATSAPP_BULK_MESSAGE,
        )
        values = await self.repo.get_settings(keys)
        text = lambda key, default="": (
            values[key].value_text if values.get(key) and values[key].value_text is not None else default
        )
        return schemas.WhatsAppSettingsResponse(
            api_key_configured=bool(decrypt_secret(text(self.WHATSAPP_API_KEY))),
            phone_number_id=text(self.WHATSAPP_PHONE_NUMBER_ID),
            template_name=text(self.WHATSAPP_TEMPLATE_NAME, "topchef_order_update"),
            language_code=text(self.WHATSAPP_LANGUAGE_CODE, "ar"),
            graph_api_version=text(self.WHATSAPP_GRAPH_API_VERSION, "v23.0"),
            enabled=text(self.WHATSAPP_ENABLED, "true").lower() == "true",
            bulk_template_name=text(self.WHATSAPP_BULK_TEMPLATE_NAME, "topchef_bulk_message"),
            password_reset_template_name=text(self.WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME, "topchef_password_reset"),
            reset_code_expiry_minutes=int(text(self.WHATSAPP_RESET_EXPIRY_MINUTES, "10")),
            bulk_send_limit=int(text(self.WHATSAPP_BULK_SEND_LIMIT, "500")),
            bulk_message=text(self.WHATSAPP_BULK_MESSAGE),
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
            text_settings = {
                self.WHATSAPP_PHONE_NUMBER_ID: (data.phone_number_id.strip(), "Meta WhatsApp phone number ID"),
                self.WHATSAPP_TEMPLATE_NAME: (data.template_name.strip(), "Approved WhatsApp utility template"),
                self.WHATSAPP_LANGUAGE_CODE: (data.language_code.strip(), "WhatsApp template language"),
                self.WHATSAPP_GRAPH_API_VERSION: (data.graph_api_version.strip(), "Meta Graph API version"),
                self.WHATSAPP_ENABLED: (str(data.enabled).lower(), "Enable automatic WhatsApp notifications"),
                self.WHATSAPP_BULK_TEMPLATE_NAME: (data.bulk_template_name.strip(), "Approved bulk message template"),
                self.WHATSAPP_PASSWORD_RESET_TEMPLATE_NAME: (data.password_reset_template_name.strip(), "Approved password reset template"),
                self.WHATSAPP_RESET_EXPIRY_MINUTES: (str(data.reset_code_expiry_minutes), "Password reset code lifetime"),
                self.WHATSAPP_BULK_SEND_LIMIT: (str(data.bulk_send_limit), "Maximum bulk recipients per send"),
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
