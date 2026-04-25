import asyncio
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from desktop.auth_service import auth_service
from desktop.local_repository import local_repository
from desktop.logger import desktop_logger as log
from desktop.printer import thermal_printer
from desktop.sync_engine import sync_engine


desktop_app = FastAPI(title="Top Chef POS Local API")
desktop_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str
    password: str


class OrderIn(BaseModel):
    items: List[dict]
    order_type: str = "hall"
    source: str = "cashier"
    customer_id: Optional[int] = None
    customer_phone: Optional[str] = None
    customer_name: Optional[str] = None
    customer_notes: Optional[str] = None
    internal_notes: Optional[str] = None
    total_amount: float
    discount_amount: float = 0
    delivery_fee: float = 0
    order_number: Optional[str] = None
    idempotency_key: Optional[str] = None
    offer_code: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    order_status: str


class CustomerCreate(BaseModel):
    name: str
    phone_number: str


class AddressCreate(BaseModel):
    address: str


class CommentCreate(BaseModel):
    full_name: str
    stars: int
    comment_text: str


class PrintRequest(BaseModel):
    order_id: int
    receipt_type: str = "customer"


class WebOrdersSettingUpdate(BaseModel):
    value_bool: bool


def _should_refresh_local_cache(max_age_seconds: int = 300) -> bool:
    last_pull = local_repository.get_meta("last_pull_timestamp")
    if not last_pull:
        return True
    try:
        last_pull_dt = datetime.fromisoformat(last_pull.replace("Z", "+00:00"))
        age_seconds = (datetime.now(last_pull_dt.tzinfo) - last_pull_dt).total_seconds()
        return age_seconds >= max_age_seconds
    except Exception:
        return True


@desktop_app.on_event("startup")
async def startup() -> None:
    auth_service.logout_runtime_session()
    sync_engine.start()


@desktop_app.on_event("shutdown")
async def shutdown() -> None:
    sync_engine.stop()


@desktop_app.get("/health/diagnostics")
def get_diagnostics() -> Dict[str, Any]:
    return sync_engine.get_health_status()


@desktop_app.post("/auth/login")
async def login(payload: LoginRequest) -> Dict[str, Any]:
    try:
        return await auth_service.login(payload.username, payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        detail = "Invalid credentials" if status_code == 401 else "Login failed"
        if status_code in (502, 503, 504):
            detail = "Cloud server unavailable"
        log.error("Login failed for %s: %s", payload.username, exc)
        raise HTTPException(status_code=401 if status_code == 401 else 503, detail=detail) from exc


@desktop_app.post("/auth/logout")
def logout() -> Dict[str, str]:
    auth_service.logout_runtime_session()
    return {"message": "Logged out successfully"}


@desktop_app.get("/menu/categories")
async def get_categories(background_tasks: BackgroundTasks) -> List[Dict[str, Any]]:
    rows = local_repository.get_categories()
    if not rows:
        sync_engine.trigger_full_sync(reason="categories-empty", wait=False)
        await asyncio.sleep(0.5)
        rows = local_repository.get_categories()
    elif _should_refresh_local_cache():
        background_tasks.add_task(sync_engine.trigger_full_sync, "categories-read", False)
    return rows


@desktop_app.get("/menu/products")
async def get_products(background_tasks: BackgroundTasks) -> List[Dict[str, Any]]:
    rows = local_repository.get_products()
    if not rows:
        sync_engine.trigger_full_sync(reason="products-empty", wait=False)
        await asyncio.sleep(0.5)
        rows = local_repository.get_products()
    elif _should_refresh_local_cache():
        background_tasks.add_task(sync_engine.trigger_full_sync, "products-read", False)
    return rows


@desktop_app.get("/offers/")
def get_offers() -> List[Dict[str, Any]]:
    return local_repository.get_offers()


@desktop_app.get("/settings/web-orders")
def get_web_orders_setting() -> bool:
    return local_repository.get_web_orders_setting()


@desktop_app.patch("/settings/web-orders")
def set_web_orders_setting(payload: WebOrdersSettingUpdate) -> Dict[str, Any]:
    return local_repository.set_web_orders_setting(payload.value_bool)


@desktop_app.get("/user/users/delivery")
def get_delivery_users() -> List[Dict[str, Any]]:
    return local_repository.get_delivery_users()


@desktop_app.get("/user/users")
def get_users() -> List[Dict[str, Any]]:
    return local_repository.get_users()


@desktop_app.get("/customers/")
def list_customers() -> List[Dict[str, Any]]:
    return local_repository.list_customers()


@desktop_app.get("/customers/by-phone/{phone}")
def get_customer_by_phone(phone: str) -> Dict[str, Any]:
    customer = local_repository.get_customer_by_phone(phone)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@desktop_app.post("/customers/")
def create_customer(payload: CustomerCreate) -> Dict[str, Any]:
    customer = local_repository.create_customer(payload.model_dump())
    sync_engine.trigger_full_sync(reason="customer-created", wait=False)
    return customer


@desktop_app.post("/customers/{customer_id}/addresses")
def add_customer_address(customer_id: int, payload: AddressCreate) -> Dict[str, Any]:
    address = local_repository.add_customer_address(customer_id, payload.address)
    sync_engine.trigger_full_sync(reason="address-created", wait=False)
    return address


@desktop_app.get("/orders/")
def list_orders(
    source: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    return local_repository.list_orders(source=source, status=status, page=page, page_size=page_size)


@desktop_app.get("/orders/{order_id}")
def get_order(order_id: int) -> Dict[str, Any]:
    order = local_repository.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@desktop_app.post("/orders/")
def create_order(payload: OrderIn) -> Dict[str, Any]:
    order_data = payload.model_dump()
    if not order_data.get("order_number"):
        order_data["order_number"] = local_repository.next_order_number()
    order = local_repository.create_order(order_data)
    sync_engine.trigger_full_sync(reason="order-created", wait=False)
    return order


@desktop_app.patch("/orders/{order_id}/status")
def update_order_status(order_id: int, payload: OrderStatusUpdate) -> Dict[str, Any]:
    order = local_repository.update_order_status(order_id, payload.order_status)
    sync_engine.trigger_full_sync(reason="order-status-updated", wait=False)
    return order


@desktop_app.post("/comments/")
def create_comment(payload: CommentCreate) -> Dict[str, Any]:
    comment = local_repository.add_comment(payload.model_dump())
    sync_engine.trigger_full_sync(reason="comment-created", wait=False)
    return comment


@desktop_app.get("/audit-logs")
def get_audit_logs(limit: int = 50) -> List[Dict[str, Any]]:
    return local_repository.get_audit_logs(limit)


@desktop_app.post("/print")
def print_order(payload: PrintRequest) -> Dict[str, Any]:
    order = local_repository.get_order(payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    accepted = thermal_printer.print_receipt(order, payload.receipt_type)
    local_repository.log_event(
        "PRINT_RECEIPT",
        None,
        {"order_id": payload.order_id, "receipt_type": payload.receipt_type, "accepted": accepted},
    )
    return {"success": accepted}


@desktop_app.post("/print/reprint-last")
def reprint_last() -> Dict[str, Any]:
    return {"success": thermal_printer.reprint_last()}


@desktop_app.post("/sync/trigger")
def trigger_sync() -> Dict[str, str]:
    sync_engine.force_sync()
    return {"status": "triggered"}


frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "frontend"))


@desktop_app.get("/")
def read_index():
    index_file = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Top Chef POS Local API - Frontend not found"}


if os.path.exists(frontend_path):
    desktop_app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
