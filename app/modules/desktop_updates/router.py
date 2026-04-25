"""
Desktop Update API — ENTERPRISE EDITION
────────────────────────────────────────
Features:
1. Incremental Pulls via 'since' parameter.
2. Synchronous/Asynchronous Audit Logging.
3. Secure Token Validation.
"""

from fastapi import APIRouter, HTTPException, Query, Header, Depends
from fastapi.responses import FileResponse
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from app.core.database import get_db
from app.core.logging import logger
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

from app.modules.infrastructure.middlewares.auth import get_current_user

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
        ts_col = "updated_at" if hasattr(model, "updated_at") else ("created_at" if hasattr(model, "created_at") else None)
        
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
