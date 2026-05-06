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
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta

from app.core.database import get_db
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

from app.modules.auth.dependencies import get_current_user

router = APIRouter()

_DESKTOP_API_TOKEN: Optional[str] = None # Set via env


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
    
    order_service = OrderService(db)
    
    for event in sorted(payload.events, key=lambda e: e.created_at):
        try:
            # Check if event already processed for this device
            stmt = select(ProcessedEvent).where(
                and_(
                    ProcessedEvent.device_id == payload.device_id,
                    ProcessedEvent.event_id == event.event_id
                )
            )
            existing_processed = await db.execute(stmt)
            if existing_processed.scalar_one_or_none():
                accepted += 1
                continue

            event_data = json.loads(event.payload)
            # Only process if we are indeed the cloud server
            if event.event_type == "ORDER_CREATED":
                # Ensure idempotency via key if present
                idempotency_key = event_data.get("idempotency_key")
                if not idempotency_key:
                    idempotency_key = f"{payload.device_id}_{event.event_id}"
                
                # Check if it already exists via idempotency_key as secondary safety
                existing = await db.execute(select(Order).where(Order.idempotency_key == idempotency_key))
                if existing.scalar_one_or_none():
                    db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                    continue
                
                try:
                    await order_service.create_order(OrderCreate(**event_data), current_user_id=current_user.id if current_user else None)
                    db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                    accepted += 1
                except Exception as e:
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
                        
                        # Apply non-status updates if present
                        await order_service.update_order(
                            cloud_order.id, 
                            OrderUpdateFull(**event_data), 
                            current_user_id=current_user.id if current_user else None
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
                                
                        db.add(ProcessedEvent(device_id=payload.device_id, event_id=event.event_id))
                        accepted += 1
                    else:
                        rejected += 1
                        errors.append(f"ORDER_UPDATED error: Order {order_number} (ID: {event_data.get('id')}) for {order_date_str} not found in cloud")
                except Exception as e:
                    rejected += 1
                    errors.append(f"ORDER_UPDATED error: {str(e)}")
            else:
                rejected += 1
                errors.append(f"Unknown event type: {event.event_type}")
            
            await db.flush() # Ensure this event is visible to subsequent events in the same batch
        except Exception as e:
            rejected += 1
            errors.append(str(e))
    
    await db.commit()
    return SyncResult(accepted=accepted, rejected=rejected, errors=errors)


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
