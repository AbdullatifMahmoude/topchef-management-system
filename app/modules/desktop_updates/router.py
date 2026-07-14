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
                    (a for a in (cloud_cust.addresses or []) if a.address == addr_text),
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
    """Forces the background sync worker to perform a master-data pull from cloud."""
    if settings.RUNTIME_MODE != "desktop":
        raise HTTPException(status_code=405, detail="Not supported in cloud mode")
    
    from app.core.events import get_outbox_sync_trigger
    get_outbox_sync_trigger().set()
    return {"status": "ok", "message": "Sync pull triggered"}


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
    
    # 2. Persistent Storage (Atomic Transaction)
    try:
        # Sync Customers
        for c_data in payload.customers:
            stmt = select(Customer).where(Customer.phone_number == c_data["phone_number"])
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if not existing:
                new_c = Customer(**{k: v for k, v in c_data.items() if k not in ("id", "is_synced")})
                db.add(new_c)
        
        # Sync Addresses
        for a_data in payload.customer_addresses:
            # We assume customer exists by now or we lookup
            new_a = CustomerAddress(**{k: v for k, v in a_data.items() if k not in ("id", "is_synced")})
            db.add(new_a)

        # Sync Orders
        for o_data in payload.orders:
            # Check if order already exists (idempotency)
            stmt = select(Order).where(Order.order_number == o_data["order_number"])
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if not existing:
                # Prepare order
                o_fields = {k: v for k, v in o_data.items() if k not in ("id", "server_id", "is_synced", "items")}
                new_o = Order(**o_fields)
                db.add(new_o)
                await db.flush() # Get order ID

                # Sync Items
                for i_data in o_data.get("items", []):
                    new_item = OrderItem(order_id=new_o.id, **{k: v for k, v in i_data.items() if k not in ("id", "order_id")})
                    db.add(new_item)

        # Sync Comments
        for cm_data in payload.comments:
            new_cm = Comment(**{k: v for k, v in cm_data.items() if k not in ("id", "is_synced")})
            db.add(new_cm)

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
            existing_processed_record = (await db.execute(stmt)).scalar_one_or_none()
            if existing_processed_record:
                if event.event_type in ["SETTING_UPDATED", "ORDER_UPDATED", "SHIFT_CREATED", "SHIFT_UPDATED"]:
                    # Inherently idempotent, safe to re-process. We just won't insert a duplicate ProcessedEvent.
                    pass
                elif event.event_type == "ORDER_CREATED":
                    # Verify the order was actually created (not just the ProcessedEvent record)
                    event_data_check = json.loads(event.payload)
                    order_number_check = event_data_check.get("order_number")
                    if order_number_check:
                        existing_order = await db.execute(
                            select(Order).where(Order.order_number == order_number_check)
                        )
                        if existing_order.scalar_one_or_none():
                            # Order exists, safe to skip
                            accepted += 1
                            continue
                        else:
                            # Order NOT found despite ProcessedEvent existing = stale record
                            logger.warning(f"ORDER_CREATED: ProcessedEvent exists but order {order_number_check} NOT found. Re-processing...")
                            await db.delete(existing_processed_record)
                            await db.flush()
                            existing_processed_record = None
                            # Fall through to process the event below
                    else:
                        accepted += 1
                        continue
                else:
                    accepted += 1
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
                if existing.scalar_one_or_none():
                    logger.info(f"ORDER_CREATED: Skipped (already exists by idempotency_key={idempotency_key})")
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
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
                                    (a for a in (cloud_cust.addresses or []) if a.address == event_data["customer_address"]),
                                    None
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
                                        delivery_person_id=event_data.get("delivery_person_id"),
                                        internal_notes=event_data.get("internal_notes")
                                    ),
                                    current_user_id=current_user.id if current_user else None
                                )
                            except Exception as status_e:
                                errors.append(f"ORDER_UPDATED status error for #{order_number}: {str(status_e)}")
                                
                        if not existing_processed_record:
                            db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                        accepted += 1
                    else:
                        rejected += 1
                        errors.append(f"ORDER_UPDATED error: Order {order_number} (ID: {event_data.get('id')}) for {order_date_str} not found in cloud")
                except Exception as e:
                    rejected += 1
                    errors.append(f"ORDER_UPDATED error: {str(e)}")
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
            elif event.event_type == "CUSTOMER_CREATED":
                try:
                    from app.modules.customer.service import CustomerService
                    from app.modules.customer.schemas import CustomerCreate
                    customer_service = CustomerService(db, redis=redis)
                    phone = event_data.get("phone_number")
                    name = event_data.get("name", "عميل")
                    if phone:
                        # Upsert: skip if phone already exists
                        try:
                            existing_cust = await customer_service.get_customer_by_phone(phone)
                            # Customer already exists, update name if different
                            if existing_cust.name != name and name:
                                existing_cust.name = name
                                await db.flush()
                                await customer_service._invalidate_cache(f"customer_profile:{existing_cust.id}")
                                await customer_service._invalidate_cache(f"customer_at_phone:{existing_cust.phone_number}")
                        except Exception:
                            # Not found, create new
                            await customer_service.create_customer(CustomerCreate(
                                name=name, phone_number=phone
                            ))
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    # Broadcast to other WebSocket clients
                    from app.core.events import order_events_manager
                    await order_events_manager.emit({
                        "type": "CUSTOMER_CREATED",
                        "data": event_data
                    })
                except Exception as e:
                    rejected += 1
                    errors.append(f"CUSTOMER_CREATED error: {str(e)}")
            elif event.event_type == "ADDRESS_CREATED":
                try:
                    from app.modules.customer.service import CustomerService
                    from app.modules.customer.schemas import CustomerAddressCreate
                    customer_service = CustomerService(db, redis=redis)
                    address_text = event_data.get("address")
                    customer_phone = event_data.get("customer_phone")
                    customer_id_remote = event_data.get("customer_id")
                    
                    # Resolve customer by phone (most reliable cross-system identifier)
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
                    
                    if resolved_customer_id and address_text:
                        # Check for duplicate address
                        existing_addr = await db.execute(
                            select(CustomerAddress).where(
                                CustomerAddress.customer_id == resolved_customer_id,
                                CustomerAddress.address == address_text
                            )
                        )
                        if not existing_addr.scalars().first():
                            await customer_service.add_address(
                                resolved_customer_id,
                                CustomerAddressCreate(address=address_text)
                            )
                    
                    if not existing_processed_record:
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    # Broadcast to other WebSocket clients
                    from app.core.events import order_events_manager
                    await order_events_manager.emit({
                        "type": "ADDRESS_CREATED",
                        "data": event_data
                    })
                except Exception as e:
                    rejected += 1
                    errors.append(f"ADDRESS_CREATED error: {str(e)}")
            elif event.event_type == "SHIFT_CREATED":
                try:
                    from app.modules.shifts.models import CashierShift
                    from datetime import date as _date

                    user_id = event_data.get("user_id")
                    target_date_str = event_data.get("target_date")
                    start_time_str = event_data.get("start_time")

                    if user_id and target_date_str and start_time_str:
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
                    rejected += 1
                    errors.append(f"SHIFT_CREATED error: {str(e)}")
            elif event.event_type == "SHIFT_UPDATED":
                try:
                    from app.modules.shifts.models import CashierShift
                    from datetime import date as _date

                    user_id = event_data.get("user_id")
                    target_date_str = event_data.get("target_date")
                    end_time_str = event_data.get("end_time")
                    start_time_str = event_data.get("start_time")
                    target_date = _date.fromisoformat(target_date_str[:10]) if target_date_str else None

                    cloud_shift = None
                    if user_id and target_date:
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
                    rejected += 1
                    errors.append(f"SHIFT_UPDATED error: {str(e)}")
            else:
                rejected += 1
                errors.append(f"Unknown event type: {event.event_type}")
            
            await db.flush() # Ensure this event is visible to subsequent events in the same batch
        except Exception as e:
            rejected += 1
            errors.append(f"Event {event.event_id} ({event.event_type}) failed: {str(e)}")
            logger.error(f"Sync event processing failed: {e}", exc_info=True)
            # If a flush failed, the transaction is doomed. We must rollback to start fresh for the next event if possible, 
            # but since we are in a single router-level transaction, one failure might doom the whole batch.
            # To be safe, we should probably commit successful ones and rollback failed ones, but SQLAlchemy async sessions
            # are tricky with partial commits in a loop if the transaction is already failed.
            await db.rollback()
            # After rollback, we need to restart the transaction for the remaining events
            continue
    
    # Acknowledge exact IDs, not merely the first ``accepted`` events.
    await db.flush()
    processed_ids = set((await db.execute(
        select(ProcessedEvent.event_id).where(
            ProcessedEvent.device_id == payload.device_id,
            ProcessedEvent.event_id.in_([event.event_id for event in payload.events]),
        )
    )).scalars().all())
    await db.commit()
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
        
        return {
            "mode": "desktop",
            "stats": stats,
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
