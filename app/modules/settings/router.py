from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.settings import schemas, service
from app.modules.infrastructure.dependencies import require_role
from app.core.enums import UserRole
from app.core.business_calendar import is_weekly_holiday
from app.modules.customer.repository import CustomerRepository
from app.modules.settings.whatsapp import whatsapp_config_ready
from app.modules.settings.whatsapp_outbox import enqueue_bulk_notifications

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("/menu-checkout", response_model=schemas.MenuCheckoutSettings)
async def get_menu_checkout_settings(db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    return await service.SettingsService(db, redis).get_menu_checkout_settings()

@router.get("/payments", response_model=schemas.PaymentSettingsResponse)
async def get_payment_settings(db: AsyncSession = Depends(get_db), redis=Depends(get_redis),
                               _current_user=Depends(require_role(UserRole.ADMIN))):
    return await service.SettingsService(db, redis).get_payment_settings()

@router.patch("/payments", response_model=schemas.PaymentSettingsResponse)
async def update_payment_settings(update_data: schemas.PaymentSettingsUpdate,
                                  db: AsyncSession = Depends(get_db), redis=Depends(get_redis),
                                  _current_user=Depends(require_role(UserRole.ADMIN))):
    return await service.SettingsService(db, redis).update_payment_settings(update_data)

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

@router.get("/whatsapp", response_model=schemas.WhatsAppSettingsResponse)
async def get_whatsapp_settings(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user = Depends(require_role(UserRole.ADMIN)),
):
    """Return non-sensitive WhatsApp configuration for the admin page."""
    return await service.SettingsService(db, redis).get_whatsapp_settings()

@router.patch("/whatsapp", response_model=schemas.WhatsAppSettingsResponse)
async def update_whatsapp_settings(
    update_data: schemas.WhatsAppSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user = Depends(require_role(UserRole.ADMIN)),
):
    """Save WhatsApp configuration without ever returning the API key."""
    return await service.SettingsService(db, redis).update_whatsapp_settings(update_data)

@router.post("/whatsapp/bulk-send", response_model=schemas.BulkSendResponse)
async def send_whatsapp_bulk_message(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    _current_user = Depends(require_role(UserRole.ADMIN)),
):
    settings_service = service.SettingsService(db, redis)
    config = await settings_service.get_whatsapp_settings()
    if not whatsapp_config_ready(config, template_name=config.bulk_template_name):
        from app.core.exceptions import ValidationError
        raise ValidationError("أكمل بيانات واتساب وفعّل الإرسال أولًا")
    if not config.bulk_message.strip():
        from app.core.exceptions import ValidationError
        raise ValidationError("اكتب نص الرسالة الجماعية واحفظ الإعدادات أولًا")
    customers = await CustomerRepository(db).list_customers()
    customers = [customer for customer in customers if customer.whatsapp_status == "enabled"]
    phones = [customer.phone_number for customer in customers[:config.bulk_send_limit]]
    queued = await enqueue_bulk_notifications(db, phones, config.bulk_message, config.bulk_template_name)
    return schemas.BulkSendResponse(queued_count=queued, message="تمت إضافة الرسائل إلى قائمة الإرسال")
