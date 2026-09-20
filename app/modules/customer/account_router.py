import json
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.exceptions import (
    AuthenticationError,
    ValidationError,
)
from app.core.redis import get_redis
from app.core.security import get_password_hash, verify_password
from app.modules.customer import models
from app.modules.customer.account_schemas import (
    CustomerAccountAvailability,
    CustomerChallengeRequest,
    CustomerChallengeResponse,
    CustomerChallengeStatus,
    CustomerCompleteRequest,
    CustomerDeviceResponse,
    CustomerLoginRequest,
    CustomerOrdersResponse,
    CustomerProfile,
    CustomerProfileUpdate,
    CustomerTokenResponse,
)
from app.modules.customer.account_security import (
    COOKIE_NAME,
    DEVICE_DAYS,
    create_device_session,
    decode_customer_access,
    rotate_device_session,
)
from app.modules.customer.phone import normalize_egyptian_phone
from app.modules.customer.repository import CustomerRepository
from app.modules.customer.schemas import CustomerAddressCreate, CustomerAddressResponse
from app.modules.offer.models import OfferUsage
from app.modules.orders.models import Order, OrderItem
from app.modules.settings.service import SettingsService
from app.modules.settings.whatsapp import inbound_verification_config_ready
from app.modules.settings.whatsapp_verification import (
    challenge_status,
    consume_verified_challenge,
    create_inbound_challenge,
)

router = APIRouter(prefix="/customer-auth", tags=["Customer Account"])
bearer = HTTPBearer(auto_error=False)


def _set_refresh_cookie(response: Response, value: str) -> None:
    response.set_cookie(COOKIE_NAME, value, max_age=DEVICE_DAYS * 86400, httponly=True,
                        secure=True, samesite="none", path="/customer-auth")


async def current_customer_payload(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not credentials:
        raise AuthenticationError("يجب تسجيل الدخول")
    return decode_customer_access(credentials.credentials)


@router.get("/availability", response_model=CustomerAccountAvailability)
async def availability(db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    config = await SettingsService(db, redis).get_whatsapp_settings()
    return CustomerAccountAvailability(available=bool(redis and inbound_verification_config_ready(config)))


@router.post("/challenges", response_model=CustomerChallengeResponse)
async def begin_challenge(data: CustomerChallengeRequest, db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    phone = normalize_egyptian_phone(data.phone)
    customer = await CustomerRepository(db).get_by_phone(phone)
    if data.purpose == "activate" and customer and customer.pin_hash:
        raise ValidationError("الحساب مفعل بالفعل؛ اختر تسجيل الدخول")
    return await create_inbound_challenge(
        db, redis, phone=phone, actor_type="customer", actor_id=customer.id if customer else None,
        purpose=data.purpose,
    )


@router.get("/challenges/{challenge_id}", response_model=CustomerChallengeStatus)
async def get_challenge_status(challenge_id: str, redis=Depends(get_redis)):
    return CustomerChallengeStatus(verified=await challenge_status(redis, challenge_id))


@router.post("/login", response_model=CustomerTokenResponse)
async def login_customer(data: CustomerLoginRequest, response: Response,
                         db: AsyncSession = Depends(get_db)):
    phone = normalize_egyptian_phone(data.phone)
    customer = await CustomerRepository(db).get_by_phone(phone)
    if not customer or not customer.pin_hash or not verify_password(data.pin, customer.pin_hash):
        raise AuthenticationError("رقم الهاتف أو PIN غير صحيح")
    access, refresh, _device = await create_device_session(db, customer.id, data.device_name)
    await db.commit()
    _set_refresh_cookie(response, refresh)
    return CustomerTokenResponse(access_token=access, customer_id=customer.id)


@router.post("/complete", response_model=CustomerTokenResponse)
async def complete_customer_auth(data: CustomerCompleteRequest, response: Response,
                                 db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    phone = normalize_egyptian_phone(data.phone)
    repo = CustomerRepository(db)
    customer = await repo.get_by_phone(phone)
    record = await consume_verified_challenge(redis, data.challenge_id, actor_type="customer", purpose=data.purpose)
    if record.get("phone") != phone:
        raise AuthenticationError("رقم الهاتف لا يطابق التحقق")
    if data.purpose == "activate":
        if not customer:
            if not data.name:
                raise ValidationError("الاسم مطلوب لإنشاء الحساب")
            customer = models.Customer(name=data.name.strip(), phone_number=phone)
            db.add(customer)
            await db.flush()
        elif record.get("actor_id") != customer.id or customer.pin_hash:
            raise AuthenticationError("الحساب مفعل بالفعل")
        customer.pin_hash = get_password_hash(data.pin)
        customer.account_activated_at = datetime.utcnow()
        if data.name:
            customer.name = data.name.strip()
    else:
        if not customer or not customer.pin_hash or record.get("actor_id") != customer.id:
            raise AuthenticationError("تعذر تأكيد الحساب")
        customer.pin_hash = get_password_hash(data.pin)
    access, refresh, _device = await create_device_session(db, customer.id, data.device_name)
    await db.commit()
    if redis:
        await redis.delete(f"customer_profile:{customer.id}")
        await redis.delete(f"customer_at_phone:{customer.phone_number}")
    _set_refresh_cookie(response, refresh)
    return CustomerTokenResponse(access_token=access, customer_id=customer.id)


@router.post("/refresh", response_model=CustomerTokenResponse)
async def refresh_customer_session(response: Response, db: AsyncSession = Depends(get_db),
                                   topchef_customer_refresh: str | None = Cookie(default=None)):
    if not topchef_customer_refresh:
        raise AuthenticationError("انتهت جلسة الجهاز")
    access, refresh, device = await rotate_device_session(db, topchef_customer_refresh)
    await db.commit()
    _set_refresh_cookie(response, refresh)
    return CustomerTokenResponse(access_token=access, customer_id=device.customer_id)


@router.post("/logout")
async def customer_logout(response: Response, payload=Depends(current_customer_payload), db: AsyncSession = Depends(get_db)):
    device = await db.get(models.CustomerDevice, payload["device_id"])
    if device:
        device.revoked_at = datetime.utcnow()
        await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/customer-auth", secure=True, samesite="none")
    return {"message": "تم تسجيل الخروج"}


async def _profile(customer_id: int, db, redis):
    key = f"customer_profile:{customer_id}"
    if redis:
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)
    customer = await CustomerRepository(db).get_by_id(customer_id)
    if not customer:
        raise AuthenticationError("الحساب غير متاح")
    data = CustomerProfile(id=customer.id, name=customer.name, phone_number=customer.phone_number,
                           whatsapp_status=customer.whatsapp_status,
                           addresses=customer.addresses).model_dump(mode="json")
    if redis:
        await redis.setex(key, 300, json.dumps(data, ensure_ascii=False))
    return data


@router.get("/me", response_model=CustomerProfile)
async def customer_me(payload=Depends(current_customer_payload), db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    return await _profile(payload["customer_id"], db, redis)


@router.patch("/me", response_model=CustomerProfile)
async def update_customer_me(data: CustomerProfileUpdate, payload=Depends(current_customer_payload),
                             db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    customer = await CustomerRepository(db).get_by_id(payload["customer_id"])
    customer.name = data.name.strip()
    await db.commit()
    if redis:
        await redis.delete(f"customer_profile:{customer.id}")
    return await _profile(customer.id, db, redis)


@router.post("/me/addresses", response_model=CustomerAddressResponse)
async def add_my_address(data: CustomerAddressCreate, payload=Depends(current_customer_payload),
                         db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    from app.modules.customer.service import CustomerService
    address = await CustomerService(db, redis).add_address(payload["customer_id"], data)
    await db.commit()
    return address


@router.delete("/me/addresses/{address_id}")
async def delete_my_address(address_id: int, payload=Depends(current_customer_payload),
                            db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    address = await db.get(models.CustomerAddress, address_id)
    if not address or address.customer_id != payload["customer_id"] or address.is_deleted:
        raise ValidationError("العنوان غير موجود")
    address.is_deleted = True
    await db.commit()
    if redis:
        await redis.delete(f"customer_profile:{payload['customer_id']}")
    return {"message": "تم حذف العنوان"}


@router.get("/me/devices", response_model=list[CustomerDeviceResponse])
async def list_my_devices(payload=Depends(current_customer_payload), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.CustomerDevice).where(
            models.CustomerDevice.customer_id == payload["customer_id"],
            models.CustomerDevice.revoked_at.is_(None),
        ).order_by(desc(models.CustomerDevice.last_used_at))
    )
    return [CustomerDeviceResponse(
        id=device.id, device_name=device.device_name, last_used_at=device.last_used_at,
        expires_at=device.expires_at, current=device.id == payload["device_id"],
    ) for device in result.scalars().all()]


@router.delete("/me/devices/{device_id}")
async def revoke_my_device(device_id: str, response: Response, payload=Depends(current_customer_payload),
                           db: AsyncSession = Depends(get_db)):
    device = await db.get(models.CustomerDevice, device_id)
    if not device or device.customer_id != payload["customer_id"]:
        raise ValidationError("الجهاز غير موجود")
    device.revoked_at = datetime.utcnow()
    await db.commit()
    if device.id == payload["device_id"]:
        response.delete_cookie(COOKIE_NAME, path="/customer-auth", secure=True, samesite="none")
    return {"message": "تم تسجيل خروج الجهاز"}


@router.get("/me/orders", response_model=CustomerOrdersResponse)
async def my_orders(payload=Depends(current_customer_payload), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Order).where(Order.customer_id == payload["customer_id"], Order.is_deleted == False)
        .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.address),
                 selectinload(Order.creator), selectinload(Order.delivery_person), selectinload(Order.modifications),
                 selectinload(Order.offer_usage).selectinload(OfferUsage.offer))
        .order_by(desc(Order.created_at)).limit(50)
    )
    return CustomerOrdersResponse(orders=list(result.scalars().all()))
