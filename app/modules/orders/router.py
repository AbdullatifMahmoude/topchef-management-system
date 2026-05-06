import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, get_optional_user
from app.modules.orders.service import OrderService
from app.modules.orders import schemas
from app.core.enums import OrderSource, OrderStatus, OrderType

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
    total, orders = await service.list_orders_paginated(
        source=source,
        status=status,
        order_type=order_type,
        page=page,
        page_size=page_size
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
            await websocket.send_json({
                "type": "ORDER_SNAPSHOT",
                "data": {
                    "total": total,
                    "orders": [
                        schemas.OrderResponse.model_validate(order).model_dump(mode="json")
                        for order in orders
                    ],
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
