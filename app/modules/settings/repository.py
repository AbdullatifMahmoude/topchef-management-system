from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.settings import models


class SettingsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_setting(self, key: str) -> models.AppSetting:
        result = await self.db.execute(
            select(models.AppSetting).where(
                models.AppSetting.key == key,
                models.AppSetting.is_deleted == False
            )
        )
        return result.scalar_one_or_none()

    async def get_settings(self, keys: tuple[str, ...]) -> dict[str, models.AppSetting]:
        result = await self.db.execute(
            select(models.AppSetting).where(
                models.AppSetting.key.in_(keys),
                models.AppSetting.is_deleted == False,
            )
        )
        return {setting.key: setting for setting in result.scalars().all()}

    async def create_or_update_setting(self, key: str, value_bool: bool, description: str | None = None) -> models.AppSetting:
        setting = await self.get_setting(key)
        if setting:
            setting.value_bool = value_bool
            if description:
                setting.description = description
        else:
            setting = models.AppSetting(key=key, value_bool=value_bool, description=description)
            self.db.add(setting)
        return setting

    async def create_or_update_text_setting(self, key: str, value_text: str, description: str | None = None) -> models.AppSetting:
        setting = await self.get_setting(key)
        if setting:
            setting.value_text = value_text
            if description:
                setting.description = description
        else:
            setting = models.AppSetting(
                key=key,
                value_bool=True,
                value_text=value_text,
                description=description,
            )
            self.db.add(setting)
        return setting
