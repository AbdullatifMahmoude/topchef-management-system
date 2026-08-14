"""
Desktop Update API — ENTERPRISE EDITION
────────────────────────────────────────
Features:
1. Incremental Pulls via 'since' parameter.
2. Synchronous/Asynchronous Audit Logging.
3. Secure Token Validation.
"""

from fastapi import APIRouter, HTTPException, Query, Header, Depends, Request
from fastapi.responses import FileResponse
from typing import Optional, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.logging import logger
from app.core.config import settings
from pydantic import BaseModel
from .service import get_latest_version, get_changelog, get_download_path
from .schemas import VersionInfo, ChangelogResponse, DesktopSyncPayload, SyncResult, MasterDataResponse

# Models
from app.modules.users.models import User
from app.modules.menu.models import Category, Product, Variant
from app.modules.offer.models import Offer
from app.modules.settings.models import AppSetting
from app.modules.customer.models import Customer, CustomerAddress
from app.modules.comments.models import Comment
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.shifts.models import CashierShift

from app.modules.auth.dependencies import get_current_user

router = APIRouter()

_DESKTOP_API_TOKEN: Optional[str] = None # Set via env


def _addresses_match(left: str | None, right: str | None) -> bool:
    return (left or "").strip() == (right or "").strip()


async def _resolve_cloud_user_id(db: AsyncSession, event_data: dict) -> int | None:
    """Resolve a cloud user by username first, then by id if it still exists."""
    username = event_data.get("username")
    if username:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()
        if user:
            return user.id

    raw_id = event_data.get("user_id")
    if raw_id is not None:
        user = await db.get(User, int(raw_id))
        if user:
            return user.id
    return None


async def _remap_order_event_foreign_keys(
    event_data: dict,
    db: AsyncSession,
    redis,
) -> dict:
    """Map desktop-local foreign keys to cloud IDs before applying order updates."""
    data = dict(event_data)

    phone = data.get("customer_phone")
    if phone:
        try:
            from app.modules.customer.service import CustomerService

            cloud_cust = await CustomerService(db, redis=redis).get_customer_by_phone(phone)
            data["customer_id"] = cloud_cust.id

            addr_text = data.get("customer_address")
            if not addr_text and isinstance(data.get("address"), dict):
                addr_text = data["address"].get("address")
            if data.get("address_id") and addr_text:
                matched = next(
                    (
                        a for a in (cloud_cust.addresses or [])
                        if _addresses_match(a.address, addr_text)
                    ),
                    None,
                )
                data["address_id"] = matched.id if matched else None
            elif data.get("address_id"):
                data["address_id"] = None
        except Exception:
            data.pop("customer_id", None)
            data.pop("address_id", None)
    else:
        data.pop("customer_id", None)
        data.pop("address_id", None)

    dp_name = data.get("delivery_person_name")
    if dp_name:
        dp_result = await db.execute(select(User).where(User.full_name == dp_name))
        cloud_dp = dp_result.scalars().first()
        data["delivery_person_id"] = cloud_dp.id if cloud_dp else None
    elif data.get("delivery_person_id"):
        # Never trust a desktop-local user id on the cloud.
        data["delivery_person_id"] = None

    return data


def _parse_shift_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


async def _broadcast_shift_event(event_type: str, event_data: dict) -> None:
    from app.core.events import order_events_manager

    await order_events_manager.emit({
        "type": event_type,
        "data": event_data,
    })


# ──────────────────────── Sync Trigger ────────────────────────

@router.post("/trigger-pull")
async def trigger_desktop_pull():
    """Forces the background sync worker to perform a full master-data pull from cloud."""
    if settings.RUNTIME_MODE != "desktop":
        raise HTTPException(status_code=405, detail="Not supported in cloud mode")

    from app.core.events import get_outbox_sync_trigger
    from app.core.sync_triggers import request_force_master_pull

    request_force_master_pull()
    get_outbox_sync_trigger().set()
    return {"status": "ok", "message": "Full sync pull triggered"}


# ──────────────────────── Incremental Pull (Master Data) ────────────────────────

@router.get("/master-data", response_model=MasterDataResponse)
async def get_master_data(
    since: Optional[datetime] = Query(None, description="Only fetch records updated after this timestamp"),
    db: AsyncSession = Depends(get_db),
    x_desktop_token: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user),
):
    """
    Returns incremental snapshot. 
    Allows either X-Desktop-Token OR a valid authenticated user.
    """
    if _DESKTOP_API_TOKEN and x_desktop_token != _DESKTOP_API_TOKEN and not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async def _fetch_incremental(model):
        stmt = select(model)
        # Handle different timestamp column names
        if hasattr(model, "updated_at"):
            ts_col = "updated_at"
        elif hasattr(model, "update_at"):
            ts_col = "update_at"
        elif hasattr(model, "created_at"):
            ts_col = "created_at"
        else:
            ts_col = None
        
        if since and ts_col:
            stmt = stmt.where(getattr(model, ts_col) > since)
        
        result = await db.execute(stmt)
        items = result.unique().scalars().all()
        
        # Serialization helper
        return [ {c.name: getattr(item, c.name) for c in item.__table__.columns} for item in items]

    logger.info(f"Desktop requested master-data pull since={since}")

    return MasterDataResponse(
        users=await _fetch_incremental(User),
        cashier_shifts=await _fetch_incremental(CashierShift),
        categories=await _fetch_incremental(Category),
        products=await _fetch_incremental(Product),
        variants=await _fetch_incremental(Variant),
        offers=await _fetch_incremental(Offer),
        app_settings=await _fetch_incremental(AppSetting),
        customers=await _fetch_incremental(Customer),
        customer_addresses=await _fetch_incremental(CustomerAddress),
        comments=await _fetch_incremental(Comment),
        orders=await _fetch_incremental(Order),
        order_items=await _fetch_incremental(OrderItem),
        order_status_history=await _fetch_incremental(OrderStatusHistory),
    )


# ──────────────────────── Atomic Sync (Push) ────────────────────────

@router.post("/sync", response_model=SyncResult)
async def desktop_sync(
    payload: DesktopSyncPayload,
    db: AsyncSession = Depends(get_db),
    x_desktop_token: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user),
):
    """
    Consolidates offline data from desktop.
    """
    if _DESKTOP_API_TOKEN and x_desktop_token != _DESKTOP_API_TOKEN and not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    logger.info(f"Received sync push from device={payload.device_id}. Orders: {len(payload.orders)}")
    
    # Legacy bulk push — prefer /sync/events. Kept for older desktops only.
    try:
        from app.modules.customer.phone import phone_lookup_candidates, normalize_egyptian_phone
        from datetime import date as date_cls

        for c_data in payload.customers:
            phone = normalize_egyptian_phone(c_data.get("phone_number")) or c_data.get("phone_number")
            candidates = phone_lookup_candidates(phone)
            stmt = select(Customer).where(Customer.phone_number.in_(candidates))
            existing = (await db.execute(stmt)).scalars().first()
            if not existing:
                fields = {k: v for k, v in c_data.items() if k not in ("id", "is_synced")}
                fields["phone_number"] = phone
                db.add(Customer(**fields))

        for a_data in payload.customer_addresses:
            cust_id = a_data.get("customer_id")
            addr_text = a_data.get("address")
            if not cust_id or not addr_text:
                continue
            existing_addr = (
                await db.execute(
                    select(CustomerAddress).where(
                        CustomerAddress.customer_id == cust_id,
                        CustomerAddress.address == addr_text,
                    )
                )
            ).scalars().first()
            if existing_addr:
                if getattr(existing_addr, "is_deleted", False):
                    existing_addr.is_deleted = False
                continue
            db.add(CustomerAddress(**{k: v for k, v in a_data.items() if k not in ("id", "is_synced")}))

        for o_data in payload.orders:
            order_number = o_data.get("order_number")
            order_date_raw = o_data.get("order_date")
            existing = None
            if order_number and order_date_raw:
                try:
                    od = date_cls.fromisoformat(str(order_date_raw)[:10])
                    existing = (
                        await db.execute(
                            select(Order).where(
                                Order.order_number == order_number,
                                Order.order_date == od,
                            )
                        )
                    ).scalars().first()
                except Exception:
                    existing = None
            if not existing and o_data.get("idempotency_key"):
                existing = (
                    await db.execute(
                        select(Order).where(Order.idempotency_key == o_data["idempotency_key"])
                    )
                ).scalars().first()
            if existing:
                continue

            o_fields = {
                k: v for k, v in o_data.items()
                if k not in ("id", "server_id", "is_synced", "items")
            }
            new_o = Order(**o_fields)
            db.add(new_o)
            await db.flush()

            for i_data in o_data.get("items", []):
                db.add(
                    OrderItem(
                        order_id=new_o.id,
                        **{k: v for k, v in i_data.items() if k not in ("id", "order_id")},
                    )
                )

        for cm_data in payload.comments:
            db.add(Comment(**{k: v for k, v in cm_data.items() if k not in ("id", "is_synced")}))

        await db.commit()
    except Exception as e:
        logger.error(f"Sync persistence failed: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Sync failed")

    accepted_count = len(payload.orders) + len(payload.customers) + len(payload.comments)
    return SyncResult(accepted=accepted_count, rejected=0, errors=[])


class OutboxEventPayload(BaseModel):
    event_id: int
    event_type: str
    topic: str
    payload: str
    created_at: datetime

class OutboxSyncRequest(BaseModel):
    device_id: str
    events: List[OutboxEventPayload]

class HeartbeatRequest(BaseModel):
    device_id: str
    version: Optional[str] = None

@router.post("/sync/events", response_model=SyncResult)
async def desktop_sync_events(
    payload: OutboxSyncRequest,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
    x_desktop_token: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user),
):
    """
    Processes Outbox events chronologically from a desktop client.
    """
    if _DESKTOP_API_TOKEN and x_desktop_token != _DESKTOP_API_TOKEN and not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    logger.info(f"Received {len(payload.events)} outbox events from device {payload.device_id}")
    accepted = 0
    rejected = 0
    errors = []
    
    import json
    from app.modules.orders.schemas import OrderCreate, OrderUpdateFull
    from app.modules.orders.service import OrderService
    from app.modules.orders.models import Order, ProcessedEvent
    
    order_service = OrderService(db, redis=redis)
    
    for event in sorted(payload.events, key=lambda e: e.created_at):
        try:
            # Check if event already processed for this device
            stmt = select(ProcessedEvent).where(
                and_(
                    ProcessedEvent.device_id == payload.device_id,
                    ProcessedEvent.event_id == event.event_id
                )
            )
            existing_processed_record = (await db.execute(stmt)).scalars().first()
            if existing_processed_record:
                if event.event_type in ["SETTING_UPDATED", "ORDER_UPDATED", "SHIFT_CREATED", "SHIFT_UPDATED"]:
                    # Inherently idempotent, safe to re-process. We just won't insert a duplicate ProcessedEvent.
                    pass
                elif event.event_type == "ORDER_CREATED":
                    # Verify the order was actually created (not just the ProcessedEvent record)
                    event_data_check = json.loads(event.payload)
                    order_number_check = event_data_check.get("order_number")
                    order_date_check = event_data_check.get("order_date")
                    idem_check = event_data_check.get("idempotency_key") or f"{payload.device_id}_{event.event_id}"

                    # Prefer unique keys — order_number alone repeats daily and
                    # scalar_one_or_none() raises "Multiple rows were found".
                    found_order = None
                    existing_by_idem = await db.execute(
                        select(Order).where(Order.idempotency_key == idem_check)
                    )
                    found_order = existing_by_idem.scalars().first()
                    if not found_order and order_number_check and order_date_check:
                        from datetime import date as date_cls
                        try:
                            od = date_cls.fromisoformat(str(order_date_check)[:10])
                            existing_by_num = await db.execute(
                                select(Order).where(
                                    Order.order_number == order_number_check,
                                    Order.order_date == od,
                                )
                            )
                            found_order = existing_by_num.scalars().first()
                        except Exception:
                            found_order = None

                        if found_order:
                            accepted += 1
                            await db.flush()
                            await db.commit()
                            continue
                        else:
                            # Order NOT found despite ProcessedEvent existing = stale record.
                            # Remove the stale acknowledgement and replay the event.
                            logger.warning(
                                f"ORDER_CREATED: ProcessedEvent exists but order {order_number_check} NOT found. Re-processing..."
                            )
                            await db.delete(existing_processed_record)
                            await db.flush()
                            existing_processed_record = None
                            # Fall through to process the event below
                    else:
                        accepted += 1
                        await db.flush()
                        await db.commit()
                        continue

            event_data = json.loads(event.payload)
            # Only process if we are indeed the cloud server
            if event.event_type == "ORDER_CREATED":
                # Ensure idempotency via key if present
                idempotency_key = event_data.get("idempotency_key")
                if not idempotency_key:
                    idempotency_key = f"{payload.device_id}_{event.event_id}"
                
                logger.info(f"Processing ORDER_CREATED: key={idempotency_key}, order_number={event_data.get('order_number')}")
                
                # Check if it already exists via idempotency_key as secondary safety
                existing = await db.execute(select(Order).where(Order.idempotency_key == idempotency_key))
                if existing.scalars().first():
                    logger.info(f"ORDER_CREATED: Skipped (already exists by idempotency_key={idempotency_key})")
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    await db.flush()
                    await db.commit()
                    continue

                try:
                    # === ID REMAPPING: Desktop local IDs -> Cloud IDs ===
                    # The event payload contains LOCAL SQLite IDs which don't match cloud Postgres IDs.
                    # We must resolve them using cross-system identifiers (phone, address text, etc.)
                    
                    # 1. Remap customer_id via phone number
                    if event_data.get("customer_phone"):
                        try:
                            from app.modules.customer.service import CustomerService
                            customer_service = CustomerService(db, redis=redis)
                            cloud_cust = await customer_service.get_customer_by_phone(event_data["customer_phone"])
                            event_data["customer_id"] = cloud_cust.id
                            logger.info(f"ORDER_CREATED: Remapped customer_id to {cloud_cust.id} via phone {event_data['customer_phone']}")
                            
                            # 2. Remap address_id via text match
                            if event_data.get("address_id") and event_data.get("customer_address"):
                                matched_addr = next(
                                    (
                                        a for a in (cloud_cust.addresses or [])
                                        if _addresses_match(a.address, event_data["customer_address"])
                                    ),
                                    None,
                                )
                                if matched_addr:
                                    event_data["address_id"] = matched_addr.id
                                    logger.info(f"ORDER_CREATED: Remapped address_id to {matched_addr.id}")
                                else:
                                    # Address doesn't exist on cloud yet, let create_order handle it
                                    event_data["address_id"] = None
                            elif event_data.get("address_id"):
                                # No address text to match, clear local ID
                                event_data["address_id"] = None
                        except Exception:
                            # Customer doesn't exist on cloud yet - let create_order handle it via phone
                            event_data["customer_id"] = None
                            event_data["address_id"] = None
                    else:
                        event_data["customer_id"] = None
                        event_data["address_id"] = None
                    
                    # 3. Remap delivery_person_id via username lookup
                    if event_data.get("delivery_person_id") and event_data.get("delivery_person_name"):
                        try:
                            from app.modules.users.models import User
                            dp_result = await db.execute(
                                select(User).where(User.full_name == event_data["delivery_person_name"])
                            )
                            cloud_dp = dp_result.scalars().first()
                            if cloud_dp:
                                event_data["delivery_person_id"] = cloud_dp.id
                                logger.info(f"ORDER_CREATED: Remapped delivery_person_id to {cloud_dp.id}")
                            else:
                                event_data["delivery_person_id"] = None
                        except Exception:
                            event_data["delivery_person_id"] = None
                    
                    # 4. Remove response-only fields that OrderCreate doesn't expect
                    for key in ["id", "created_at", "order_status", "subtotal", "discount_amount", 
                                "total_amount", "creator_name", "delivery_person_name", "address"]:
                        event_data.pop(key, None)
                    # Clean item response fields
                    for item in event_data.get("items", []):
                        item.pop("id", None)
                        item.pop("total_price", None)
                    
                    # 5. Set the idempotency_key so the cloud can track this order
                    event_data["idempotency_key"] = idempotency_key
                    
                    order_create_data = OrderCreate(**event_data)
                    logger.info(f"ORDER_CREATED: Creating order on cloud: num={order_create_data.order_number}, source={order_create_data.source}, items={len(order_create_data.items)}")
                    created = await order_service.create_order(order_create_data, current_user_id=current_user.id if current_user else None)
                    logger.info(f"ORDER_CREATED: Successfully created cloud order ID={created.id}, num={created.order_number}")
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                except Exception as e:
                    logger.error(f"ORDER_CREATED error: {str(e)}", exc_info=True)
                    rejected += 1
                    errors.append(f"ORDER_CREATED error: {str(e)}")
                    raise
            elif event.event_type == "ORDER_UPDATED":
                try:
                    # 1. Try to find the order by number (the most reliable way across systems)
                    cloud_order = None
                    order_number = event_data.get("order_number")
                    order_date_str = event_data.get("order_date")
                    
                    if order_number and order_date_str:
                        from datetime import date
                        try:
                            order_date = date.fromisoformat(order_date_str[:10])
                            cloud_order = await order_service.repository.get_by_number(order_number, order_date)
                        except Exception:
                            pass
                    
                    # 1.5 Fallback: Try by remote ID if number fails
                    if not cloud_order and event_data.get("id"):
                        try:
                            fallback_order = await order_service.repository.get_by_id(int(event_data.get("id")))
                            # Verify that the order number matches to prevent ID collision mismatches
                            if fallback_order and fallback_order.order_number == order_number:
                                cloud_order = fallback_order
                        except Exception:
                            pass

                    # 2. Update if found
                    if cloud_order:
                        from app.modules.orders.schemas import OrderUpdateFull, OrderUpdate

                        remapped = await _remap_order_event_foreign_keys(event_data, db, redis)
                        update_fields = {
                            key: value
                            for key, value in remapped.items()
                            if key in OrderUpdateFull.model_fields
                        }
                        if update_fields:
                            await order_service.update_order(
                                cloud_order.id,
                                OrderUpdateFull(**update_fields),
                                current_user_id=current_user.id if current_user else None,
                            )
                        
                        # Apply status updates if present
                        # Robust comparison: extract value and normalize to lower case
                        current_status = str(getattr(cloud_order.order_status, "value", cloud_order.order_status)).lower()
                        new_status = str(event_data.get("order_status", "")).lower()

                        if new_status and new_status != current_status:
                            try:
                                await order_service.update_order_status(
                                    cloud_order.id,
                                    OrderUpdate(
                                        order_status=new_status,
                                        delivery_person_id=remapped.get("delivery_person_id"),
                                        internal_notes=event_data.get("internal_notes")
                                    ),
                                    current_user_id=current_user.id if current_user else None
                                )
                            except Exception as status_e:
                                errors.append(f"ORDER_UPDATED status error for #{order_number}: {str(status_e)}")
                                raise
                                
                        if not existing_processed_record:
                            db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                        accepted += 1
                    else:
                        rejected += 1
                        errors.append(f"ORDER_UPDATED error: Order {order_number} (ID: {event_data.get('id')}) for {order_date_str} not found in cloud")
                        raise RuntimeError(f"ORDER_UPDATED not found: {order_number}")
                except Exception as e:
                    if not any(str(e) in err or err.startswith("ORDER_UPDATED") for err in errors[-1:]):
                        rejected += 1
                        errors.append(f"ORDER_UPDATED error: {str(e)}")
                    raise
            elif event.event_type == "SETTING_UPDATED":
                try:
                    from app.modules.settings.service import SettingsService
                    settings_service = SettingsService(db, redis=redis) 
                    await settings_service.toggle_web_orders(event_data.get("value_bool", True))
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                except Exception as e:
                    rejected += 1
                    errors.append(f"SETTING_UPDATED error: {str(e)}")
                    raise
            elif event.event_type == "CUSTOMER_CREATED":
                try:
                    from app.modules.customer.service import CustomerService
                    from app.modules.customer.schemas import CustomerCreate
                    customer_service = CustomerService(db, redis=redis)
                    phone = event_data.get("phone_number")
                    name = event_data.get("name", "عميل")
                    if not phone:
                        rejected += 1
                        errors.append("CUSTOMER_CREATED error: missing phone_number")
                        raise RuntimeError("CUSTOMER_CREATED missing phone")
                    try:
                        existing_cust = await customer_service.get_customer_by_phone(phone)
                        if existing_cust.name != name and name:
                            existing_cust.name = name
                            await db.flush()
                            await customer_service._invalidate_cache(f"customer_profile:{existing_cust.id}")
                            await customer_service._invalidate_cache(f"customer_at_phone:{existing_cust.phone_number}")
                    except Exception:
                        # Phone numbers may be edited offline.  In that case the
                        # new number cannot find the cloud row, but the previous
                        # number identifies the same customer and must be updated
                        # rather than creating a duplicate customer.
                        previous_phone = event_data.get("previous_phone_number")
                        previous_customer = None
                        if previous_phone:
                            try:
                                previous_customer = await customer_service.get_customer_by_phone(previous_phone)
                            except Exception:
                                previous_customer = None

                        if previous_customer:
                            from app.modules.customer.phone import normalize_egyptian_phone

                            previous_customer.phone_number = normalize_egyptian_phone(phone) or phone.strip()
                            if name:
                                previous_customer.name = name
                            await db.flush()
                            await customer_service._invalidate_cache(f"customer_profile:{previous_customer.id}")
                            await customer_service._invalidate_cache(f"customer_at_phone:{previous_phone}")
                        else:
                            await customer_service.create_customer(CustomerCreate(
                                name=name, phone_number=phone
                            ))
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    from app.core.events import order_events_manager
                    await order_events_manager.emit({
                        "type": "CUSTOMER_CREATED",
                        "data": event_data
                    })
                except Exception as e:
                    if "CUSTOMER_CREATED error:" not in str(e):
                        rejected += 1
                        errors.append(f"CUSTOMER_CREATED error: {str(e)}")
                    raise
            elif event.event_type == "ADDRESS_CREATED":
                try:
                    from app.modules.customer.service import CustomerService
                    from app.modules.customer.schemas import CustomerAddressCreate
                    customer_service = CustomerService(db, redis=redis)
                    address_text = (event_data.get("address") or "").strip()
                    customer_phone = event_data.get("customer_phone")
                    customer_id_remote = event_data.get("customer_id")
                    
                    resolved_customer_id = None
                    if customer_phone:
                        try:
                            cust = await customer_service.get_customer_by_phone(customer_phone)
                            resolved_customer_id = cust.id
                        except Exception:
                            pass
                    
                    if not resolved_customer_id and customer_id_remote:
                        try:
                            cust = await customer_service.get_customer(int(customer_id_remote))
                            resolved_customer_id = cust.id
                        except Exception:
                            pass
                    
                    if not resolved_customer_id or not address_text:
                        rejected += 1
                        errors.append(
                            f"ADDRESS_CREATED error: unresolved customer or missing address (phone={customer_phone})"
                        )
                        raise RuntimeError("ADDRESS_CREATED unresolved")

                    existing_addr = (
                        await db.execute(
                            select(CustomerAddress).where(
                                CustomerAddress.customer_id == resolved_customer_id,
                                CustomerAddress.address == address_text,
                            )
                        )
                    ).scalars().first()
                    if existing_addr:
                        if getattr(existing_addr, "is_deleted", False):
                            existing_addr.is_deleted = False
                            await db.flush()
                    else:
                        await customer_service.add_address(
                            resolved_customer_id,
                            CustomerAddressCreate(address=address_text)
                        )
                    
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    from app.core.events import order_events_manager
                    await order_events_manager.emit({
                        "type": "ADDRESS_CREATED",
                        "data": event_data
                    })
                except Exception as e:
                    if "ADDRESS_CREATED error:" not in str(e):
                        rejected += 1
                        errors.append(f"ADDRESS_CREATED error: {str(e)}")
                    raise
            elif event.event_type == "SHIFT_CREATED":
                try:
                    from app.modules.shifts.models import CashierShift
                    from datetime import date as _date

                    user_id = await _resolve_cloud_user_id(db, event_data)
                    target_date_str = event_data.get("target_date")
                    start_time_str = event_data.get("start_time")

                    if not user_id or not target_date_str or not start_time_str:
                        rejected += 1
                        errors.append(
                            "SHIFT_CREATED error: unresolved user or missing fields "
                            f"(username={event_data.get('username')}, user_id={event_data.get('user_id')})"
                        )
                        raise RuntimeError("SHIFT_CREATED unresolved")

                    target_date = _date.fromisoformat(target_date_str[:10])
                    start_time = _parse_shift_datetime(start_time_str)

                    open_shift = await db.execute(
                        select(CashierShift).where(
                            CashierShift.user_id == user_id,
                            CashierShift.target_date == target_date,
                            CashierShift.end_time.is_(None),
                        )
                    )
                    if not open_shift.scalars().first():
                        existing_shift = await db.execute(
                            select(CashierShift).where(
                                CashierShift.user_id == user_id,
                                CashierShift.target_date == target_date,
                                CashierShift.start_time == start_time,
                            )
                        )
                        if not existing_shift.scalars().first():
                            db.add(
                                CashierShift(
                                    user_id=user_id,
                                    target_date=target_date,
                                    start_time=start_time,
                                )
                            )

                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    await _broadcast_shift_event("SHIFT_CREATED", event_data)
                except Exception as e:
                    if "SHIFT_CREATED error:" not in str(e):
                        rejected += 1
                        errors.append(f"SHIFT_CREATED error: {str(e)}")
                    raise
            elif event.event_type == "SHIFT_UPDATED":
                try:
                    from app.modules.shifts.models import CashierShift
                    from datetime import date as _date

                    user_id = await _resolve_cloud_user_id(db, event_data)
                    target_date_str = event_data.get("target_date")
                    end_time_str = event_data.get("end_time")
                    start_time_str = event_data.get("start_time")
                    target_date = _date.fromisoformat(target_date_str[:10]) if target_date_str else None

                    if not user_id or not target_date:
                        rejected += 1
                        errors.append(
                            "SHIFT_UPDATED error: unresolved user or missing target_date "
                            f"(username={event_data.get('username')})"
                        )
                        raise RuntimeError("SHIFT_UPDATED unresolved")

                    cloud_shift = None
                    if "end_time" in event_data and end_time_str is None:
                        open_result = await db.execute(
                            select(CashierShift).where(
                                CashierShift.user_id == user_id,
                                CashierShift.target_date == target_date,
                                CashierShift.end_time.is_(None),
                            )
                        )
                        cloud_shift = open_result.scalars().first()
                        if not cloud_shift:
                            start_time = _parse_shift_datetime(start_time_str) or datetime.utcnow()
                            closed_result = await db.execute(
                                select(CashierShift)
                                .where(
                                    CashierShift.user_id == user_id,
                                    CashierShift.target_date == target_date,
                                )
                                .order_by(CashierShift.id.desc())
                            )
                            cloud_shift = closed_result.scalars().first()
                            if cloud_shift:
                                cloud_shift.end_time = None
                                cloud_shift.start_time = start_time
                            else:
                                cloud_shift = CashierShift(
                                    user_id=user_id,
                                    target_date=target_date,
                                    start_time=start_time,
                                )
                                db.add(cloud_shift)
                    elif end_time_str:
                        open_result = await db.execute(
                            select(CashierShift)
                            .where(
                                CashierShift.user_id == user_id,
                                CashierShift.target_date == target_date,
                                CashierShift.end_time.is_(None),
                            )
                            .order_by(CashierShift.id.desc())
                        )
                        cloud_shift = open_result.scalars().first()
                        if cloud_shift:
                            cloud_shift.end_time = _parse_shift_datetime(end_time_str)

                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    await _broadcast_shift_event("SHIFT_UPDATED", event_data)
                except Exception as e:
                    if "SHIFT_UPDATED error:" not in str(e):
                        rejected += 1
                        errors.append(f"SHIFT_UPDATED error: {str(e)}")
                    raise
            else:
                rejected += 1
                errors.append(f"Unknown event type: {event.event_type}")
                raise RuntimeError(f"Unknown event type: {event.event_type}")
            
            # Commit each event so a later failure cannot wipe earlier successes.
            await db.flush()
            await db.commit()
        except Exception as e:
            # Handlers record rejected/errors before re-raising. Only count unexpected failures here.
            logger.error(f"Sync event processing failed: {e}", exc_info=True)
            already_recorded = any(
                f"Event {event.event_id}" in err or f"{event.event_type} error" in err
                for err in errors
            )
            if not already_recorded:
                rejected += 1
                errors.append(f"Event {event.event_id} ({event.event_type}) failed: {str(e)}")
            await db.rollback()
            continue
    
    # Acknowledge exact IDs that were durably processed for this device.
    processed_ids = set((await db.execute(
        select(ProcessedEvent.event_id).where(
            ProcessedEvent.device_id == payload.device_id,
            ProcessedEvent.event_id.in_([event.event_id for event in payload.events]),
        )
    )).scalars().all())
    return SyncResult(
        accepted=accepted,
        rejected=rejected,
        errors=errors,
        accepted_event_ids=sorted(processed_ids),
    )


@router.post("/sync/heartbeat")
async def desktop_heartbeat(
    payload: HeartbeatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_desktop_token: Optional[str] = Header(None)
):
    """
    Updates the last_seen timestamp for a device.
    """
    if _DESKTOP_API_TOKEN and x_desktop_token != _DESKTOP_API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    from app.modules.orders.models import ActiveDevice
    
    stmt = select(ActiveDevice).where(ActiveDevice.device_id == payload.device_id)
    device = (await db.execute(stmt)).scalar_one_or_none()
    
    if not device:
        device = ActiveDevice(device_id=payload.device_id, version=payload.version)
        db.add(device)
    else:
        device.version = payload.version
        device.last_seen = datetime.now() # onupdate handles this but we force it

    if request.client:
        device.ip_address = request.client.host
        
    await db.commit()
    return {"status": "ok"}


@router.get("/sync/status")
async def get_sync_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns sync metrics.
    On Desktop: shows Outbox stats.
    On Cloud: shows ProcessedEvent stats.
    """
    if settings.RUNTIME_MODE == "desktop":
        from app.modules.orders.models import OutboxEvent, OutboxEventStatus
        from app.modules.sync.models import SyncQuarantine
        from app.core.sync_health import sync_health
        from sqlalchemy import func
        
        # Summary counts
        stmt = select(
            OutboxEvent.status,
            func.count(OutboxEvent.id)
        ).group_by(OutboxEvent.status)
        
        results = await db.execute(stmt)
        stats = {status.value if hasattr(status, 'value') else str(status): count for status, count in results.all()}
        
        # Latest failures for review
        stmt_failed = select(OutboxEvent).where(OutboxEvent.status == OutboxEventStatus.FAILED).order_by(OutboxEvent.created_at.desc()).limit(20)
        failed_items = (await db.execute(stmt_failed)).scalars().all()

        quarantined = (
            await db.execute(
                select(SyncQuarantine)
                .where(SyncQuarantine.quarantined.is_(True))
                .order_by(SyncQuarantine.last_failed_at.desc())
                .limit(20)
            )
        ).scalars().all()
        
        return {
            "mode": "desktop",
            "stats": stats,
            "health": sync_health.to_dict(),
            "quarantined_rows": [
                {
                    "table": q.table_name,
                    "record_key": q.record_key,
                    "error": q.error_message,
                    "failure_count": q.failure_count,
                    "last_failed_at": q.last_failed_at.isoformat() if q.last_failed_at else None,
                }
                for q in quarantined
            ],
            "failed_events": [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "topic": e.topic,
                    "error": e.error_message,
                    "retry_count": e.retry_count,
                    "created_at": e.created_at.isoformat() if e.created_at else None
                } for e in failed_items
            ]
        }
    else:
        from app.modules.orders.models import ProcessedEvent, ActiveDevice
        from sqlalchemy import func
        
        # Get counts from ProcessedEvent
        stmt_counts = select(
            ProcessedEvent.device_id,
            func.count(ProcessedEvent.id)
        ).group_by(ProcessedEvent.device_id)
        
        results_counts = await db.execute(stmt_counts)
        device_counts = {device: count for device, count in results_counts.all()}
        
        # Get actual active devices
        try:
            stmt_active = select(ActiveDevice)
            results_active = await db.execute(stmt_active)
            active_list = results_active.scalars().all()
        except Exception as e:
            logger.warning(f"Could not fetch active devices: {e}")
            active_list = []
        
        device_stats = []
        online_cutoff = datetime.now() - timedelta(minutes=2)
        for dev in active_list:
            device_stats.append({
                "device_id": dev.device_id,
                "count": device_counts.get(dev.device_id, 0),
                "last_seen": dev.last_seen.isoformat() if dev.last_seen else None,
                "version": dev.version,
                "ip_address": dev.ip_address,
                "online": bool(dev.last_seen and dev.last_seen >= online_cutoff),
            })

        device_stats.sort(key=lambda dev: dev.get("last_seen") or "", reverse=True)
            
        return {
            "mode": "cloud",
            "device_stats": device_stats,
            "total_devices": len(device_stats),
            "online_devices": sum(1 for dev in device_stats if dev.get("online")),
        }


# ──────────────────────── Version & Download ────────────────────────

@router.get("/version", response_model=VersionInfo)
async def desktop_version(
    x_desktop_token: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user)
):
    if _DESKTOP_API_TOKEN and x_desktop_token != _DESKTOP_API_TOKEN and not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return get_latest_version()


@router.get("/download")
async def desktop_download(
    filename: str = Query("TopChefSetup.exe"),
    x_desktop_token: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user)
):
    if _DESKTOP_API_TOKEN and x_desktop_token != _DESKTOP_API_TOKEN and not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    path = get_download_path(filename)
    if not path: raise HTTPException(404)
    return FileResponse(path, media_type="application/octet-stream", filename=filename)
