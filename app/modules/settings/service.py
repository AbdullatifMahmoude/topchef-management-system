import contextlib
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.settings.repository import SettingsRepository
from app.modules.settings import schemas
from app.core.logging import logger

class SettingsService:
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
            
            # Invalidate Cache
            if self.redis:
                try:
                    await self.redis.setex("settings:web_orders_enabled", 3600, str(enabled).lower())
                except Exception:
                    pass
            
            logger.info(f"Web orders status toggled to: {enabled}")
            return setting
