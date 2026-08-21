from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.settings import schemas, service
from app.modules.infrastructure.dependencies import require_role
from app.core.enums import UserRole
from app.core.business_calendar import is_weekly_holiday

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("/web-orders", response_model=bool)
async def get_web_orders_status(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """Check if web orders are currently enabled."""
    if is_weekly_holiday():
        return False
    settings_service = service.SettingsService(db, redis)
    return await settings_service.get_web_orders_status()

@router.patch("/web-orders", response_model=schemas.SettingResponse)
async def toggle_web_orders(
    update_data: schemas.SettingUpdate,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user = Depends(require_role(UserRole.ADMIN, UserRole.CASHIER))
):
    """Toggle online orders availability (Admin and Cashier only)."""
    settings_service = service.SettingsService(db, redis)
    return await settings_service.toggle_web_orders(update_data.value_bool)
