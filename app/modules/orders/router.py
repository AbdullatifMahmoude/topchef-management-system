import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, get_optional_user
from app.modules.orders.service import OrderService
from app.modules.orders import schemas
from app.core.enums import OrderSource, OrderStatus, OrderType, UserRole

from app.core.redis import get_redis
from app.modules.orders.dependencies import get_order_service
from app.core.events import order_events_manager


router = APIRouter(prefix="/orders", tags=["Orders"])

@router.post("/", response_model=schemas.OrderResponse)
async def create_order(
    order_data: schemas.OrderCreate,
    service: OrderService = Depends(get_order_service),
    current_user: Optional[any] = Depends(get_optional_user)
):
    user_id = current_user.id if current_user else None
    return await service.create_order(order_data, current_user_id=user_id)

@router.get("/", response_model=schemas.OrderListResponse)  # Change to dict with pagination
async def list_orders(
    source: Optional[OrderSource] = None,
    status: Optional[OrderStatus] = None,
    order_type: Optional[OrderType] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    service: OrderService = Depends(get_order_service),
    current_user: any = Depends(get_current_user)
):
    cashier_id = None
    if current_user and hasattr(current_user, 'role') and current_user.role == UserRole.CASHIER:
        cashier_id = current_user.id

    total, orders = await service.list_orders_paginated(
        source=source,
        status=status,
        order_type=order_type,
        page=page,
        page_size=page_size,
        cashier_id=cashier_id
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "orders": orders
    }

@router.get("/{order_id}", response_model=schemas.OrderDetailResponse)
async def get_order_detail(
    order_id: int,
    service: OrderService = Depends(get_order_service),
    current_user: any = Depends(get_current_user)
):
    return await service.get_order(order_id)

@router.get("/dashboard/stats")
async def get_dashboard_stats(
    service: OrderService = Depends(get_order_service),
    current_user: any = Depends(get_current_user)
):
    return await service.get_today_stats()

@router.get("/dashboard/today", response_model=schemas.OrderListResponse)
async def list_dashboard_today_orders(
    source: Optional[OrderSource] = None,
    status: Optional[OrderStatus] = None,
    order_type: Optional[OrderType] = None,
    service: OrderService = Depends(get_order_service),
    current_user: any = Depends(get_current_user)
):
    cashier_id = None
    if current_user and hasattr(current_user, 'role') and current_user.role == UserRole.CASHIER:
        cashier_id = current_user.id

    orders = await service.list_orders_for_business_day(
        source=source,
        status=status,
        order_type=order_type,
        cashier_id=cashier_id,
    )

    return {
        "total": len(orders),
        "page": 1,
        "page_size": len(orders),
        "orders": orders,
    }

@router.get("/riders/stats")
async def get_rider_stats(
    db: AsyncSession = Depends(get_db),
    current_user: any = Depends(get_current_user)
):
    """Return the live delivery desk snapshot for the current business day."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, and_, or_
    from sqlalchemy.orm import selectinload
    from app.modules.orders.models import Order
    from app.modules.users.models import User
    from app.core.enums import OrderStatus, OrderType, UserRole, PaymentMethod
    
    # Calculate business day start (5 AM boundary)
    # Using Egypt timezone (UTC+3)
    tz = timezone(timedelta(hours=3))
    now = datetime.now(tz).replace(tzinfo=None)
    business_day_start = now.replace(hour=5, minute=0, second=0, microsecond=0)
    
    # If current time is before 5 AM, the business day started yesterday at 5 AM
    if now.hour < 5:
        business_day_start = business_day_start - timedelta(days=1)
    
    # `order_date` is set from the 5 AM business-day boundary when the order is
    # created. It is the authoritative order response.
    # browser/device timestamps or page-limited frontend lists.
    business_date = business_day_start.date()
    users_result = await db.execute(
        select(User)
        .where(and_(User.role == UserRole.DELIVERY, User.is_deleted == False))
        .order_by(User.full_name, User.username)
    )
    delivery_users = list(users_result.scalars().all())

    orders_result = await db.execute(
        select(Order).options(selectinload(Order.delivery_person), selectinload(Order.address))
        .where(and_(
            Order.order_date == business_date,
            Order.is_deleted == False,
            or_(Order.order_type == OrderType.DELIVERY, Order.delivery_person_id.isnot(None)),
        ))
        .order_by(Order.created_at.desc())
    )
    day_orders = list(orders_result.scalars().all())

    riders: dict[int, dict] = {
        user.id: {
            "id": user.id,
            "name": user.full_name or user.username,
            "username": user.username,
            "phone": user.phone,
            "availability": "available",
            "active_orders": 0,
            "delivered_orders": 0,
            "total_orders": 0,
            "total_amount": 0.0,
            "order_value": 0.0,
            "cash_amount": 0.0,
            "digital_amount": 0.0,
            "delivery_fees": 0.0,
            "order_numbers": [],
        }
        for user in delivery_users
    }

    operational_orders = []
    for order in day_orders:
        if order.order_status == OrderStatus.CANCELLED:
            continue
        rider = riders.get(order.delivery_person_id)
        if not rider and order.delivery_person_id:
            rider = {
                "id": order.delivery_person_id,
                "name": order.delivery_person_name or "مندوب غير نشط",
                "username": "", "phone": "", "availability": "available",
                "active_orders": 0, "delivered_orders": 0, "total_orders": 0,
                "total_amount": 0.0, "order_value": 0.0, "cash_amount": 0.0,
                "digital_amount": 0.0, "delivery_fees": 0.0, "order_numbers": [],
            }
            riders[order.delivery_person_id] = rider
        if rider:
            order_value = max(0.0, float(order.total_amount or 0) - float(order.delivery_fee or 0))
            rider["total_orders"] += 1
            rider["total_amount"] += float(order.total_amount or 0)
            rider["order_value"] += order_value
            rider["delivery_fees"] += float(order.delivery_fee or 0)
            rider["order_numbers"].append(order.order_number or str(order.id))
            if order.order_status == OrderStatus.DELIVERED:
                rider["delivered_orders"] += 1
            elif order.order_status in [OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY]:
                rider["active_orders"] += 1
                rider["availability"] = "busy"
            if order.payment_method == PaymentMethod.CASH:
                rider["cash_amount"] += order_value
            else:
                rider["digital_amount"] += order_value

        if order.order_status in [OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY]:
            age_minutes = max(0, int((now - order.created_at).total_seconds() // 60))
            operational_orders.append({
                "id": order.id,
                "order_number": order.order_number or str(order.id),
                "customer_name": order.customer_name or "عميل",
                "customer_phone": order.customer_phone,
                "customer_address": order.customer_address,
                "status": order.order_status.value,
                "payment_method": order.payment_method.value,
                "total_amount": float(order.total_amount or 0),
                "delivery_fee": float(order.delivery_fee or 0),
                "rider_id": order.delivery_person_id,
                "rider_name": order.delivery_person_name,
                "created_at": order.created_at.isoformat(),
                "age_minutes": age_minutes,
            })

    non_cancelled_delivery_orders = [order for order in day_orders if order.order_status != OrderStatus.CANCELLED]
    unassigned = sum(1 for order in non_cancelled_delivery_orders if not order.delivery_person_id)
    assigned = sum(1 for order in non_cancelled_delivery_orders if order.delivery_person_id)
    out_for_delivery = sum(1 for order in operational_orders if order["status"] == OrderStatus.OUT_FOR_DELIVERY.value)
    
    return {
        "business_day_start": business_day_start.isoformat(),
        "business_date": business_date.isoformat(),
        "stats": list(riders.values()),
        "orders": operational_orders,
        "summary": {
            "active_riders": sum(1 for rider in riders.values() if rider["availability"] == "busy"),
            "available_riders": sum(1 for rider in riders.values() if rider["availability"] == "available"),
            "unassigned_orders": unassigned,
            "assigned_orders": assigned,
            "total_delivery_orders": len(non_cancelled_delivery_orders),
            "cancelled_delivery_orders": sum(1 for order in day_orders if order.order_status == OrderStatus.CANCELLED),
            "orders_value": sum(max(0.0, float(order.total_amount or 0) - float(order.delivery_fee or 0)) for order in non_cancelled_delivery_orders),
            "out_for_delivery": out_for_delivery,
            "delivered_orders": sum(rider["delivered_orders"] for rider in riders.values()),
            "cash_to_collect": sum(rider["cash_amount"] for rider in riders.values()),
        },
    }

@router.patch("/{order_id}", response_model=schemas.OrderResponse)
async def update_order(
    order_id: int,
    update_data: schemas.OrderUpdateFull,
    service: OrderService = Depends(get_order_service),
    current_user: any = Depends(get_current_user)
):
    user_id = current_user.id if current_user else None
    return await service.update_order(order_id, update_data, current_user_id=user_id)

@router.patch("/{order_id}/status", response_model=schemas.OrderResponse)
async def update_order_status(
    order_id: int,
    update_data: schemas.OrderUpdate,
    service: OrderService = Depends(get_order_service),
    current_user: any = Depends(get_current_user)
):
    user_id = current_user.id if current_user else None
    return await service.update_order_status(order_id, update_data, current_user_id=user_id)

@router.websocket("/ws")
@router.websocket("/ws/{channel}")
async def websocket_orders(
    websocket: WebSocket,
    channel: str = "default",
    service: OrderService = Depends(get_order_service),
):
    await order_events_manager.connect(websocket, channel)
    try:
        if channel in {"cashier", "admin", "default"}:
            total, orders = await service.list_orders_paginated(page=1, page_size=500)
            
            validated_orders = []
            for order in orders:
                try:
                    validated_orders.append(
                        schemas.OrderResponse.model_validate(order).model_dump(mode="json")
                    )
                except Exception as e:
                    logger.warning(f"Skipping malformed order {getattr(order, 'id', 'unknown')} in WS snapshot: {e}")

            await websocket.send_json({
                "type": "ORDER_SNAPSHOT",
                "data": {
                    "total": total,
                    "orders": validated_orders,
                },
            })

        while True:
            message = await websocket.receive_text()
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue

            if payload.get("type") in {"heartbeat", "HEARTBEAT"}:
                await websocket.send_json({"type": "HEARTBEAT_ACK"})
    except WebSocketDisconnect:
        pass
    finally:
        await order_events_manager.disconnect(websocket, channel)
