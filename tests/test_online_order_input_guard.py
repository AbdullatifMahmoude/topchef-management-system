from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.enums import DiscountType, OrderSource, OrderType, UserRole
from app.core.exceptions import ValidationError
from app.modules.auth.dependencies import get_optional_user
from app.modules.menu.service import ProductService
from app.modules.orders.dependencies import get_order_service
from app.modules.orders.router import router as order_router
from app.modules.orders.schemas import OrderCreate, OrderItemCreate
from app.modules.orders.service import OrderService


def test_guest_cannot_create_cashier_order():
    isolated_app = FastAPI()
    isolated_app.include_router(order_router)
    fake_service = SimpleNamespace(create_order=AsyncMock(side_effect=AssertionError("cashier order reached service")))
    isolated_app.dependency_overrides[get_order_service] = lambda: fake_service
    isolated_app.dependency_overrides[get_optional_user] = lambda: None

    response = TestClient(isolated_app).post("/orders/", json={
        "order_type": "takeaway", "source": "cashier",
        "items": [{"product_id": 1, "quantity": 1, "unit_price": "100"}],
    })
    assert response.status_code == 403
    fake_service.create_order.assert_not_called()


@pytest.mark.parametrize("role", [UserRole.DELIVERY, "customer"])
def test_non_cashier_role_cannot_create_cashier_order(role):
    isolated_app = FastAPI()
    isolated_app.include_router(order_router)
    fake_service = SimpleNamespace(create_order=AsyncMock(side_effect=AssertionError("unauthorized order reached service")))
    isolated_app.dependency_overrides[get_order_service] = lambda: fake_service
    isolated_app.dependency_overrides[get_optional_user] = lambda: SimpleNamespace(id=17, role=role)

    response = TestClient(isolated_app).post("/orders/", json={
        "order_type": "takeaway", "source": "cashier",
        "items": [{"product_id": 1, "quantity": 1, "unit_price": "100"}],
    })
    assert response.status_code == 403
    fake_service.create_order.assert_not_called()


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.CASHIER])
def test_staff_role_reaches_cashier_order_service(role):
    isolated_app = FastAPI()
    isolated_app.include_router(order_router)
    fake_service = SimpleNamespace(create_order=AsyncMock(side_effect=RuntimeError("authorized service reached")))
    isolated_app.dependency_overrides[get_order_service] = lambda: fake_service
    isolated_app.dependency_overrides[get_optional_user] = lambda: SimpleNamespace(id=17, role=role)

    with pytest.raises(RuntimeError, match="authorized service reached"):
        TestClient(isolated_app).post("/orders/", json={
            "order_type": "takeaway", "source": "cashier",
            "items": [{"product_id": 1, "quantity": 1, "unit_price": "100"}],
        })
    fake_service.create_order.assert_called_once()


@pytest.mark.asyncio
async def test_online_order_cannot_supply_manual_discount(monkeypatch):
    monkeypatch.setattr("app.modules.orders.service.is_weekly_holiday", lambda *_: False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            service = OrderService(db)
            service.settings_service.get_menu_checkout_settings = AsyncMock(return_value=SimpleNamespace(
                ordering_enabled=True, instapay_enabled=True, wallet_enabled=True,
            ))
            service._validate_order_items = AsyncMock(side_effect=AssertionError("invalid discount reached pricing"))
            data = OrderCreate(
                order_type=OrderType.TAKEAWAY, source=OrderSource.ONLINE,
                items=[OrderItemCreate(product_id=1, quantity=1, unit_price=Decimal(100))],
                manual_discount_type=DiscountType.FIXED, manual_discount_value=Decimal(50),
            )
            with pytest.raises(ValidationError, match="الخصم اليدوي"):
                await service.create_order(data)
            service._validate_order_items.assert_not_called()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_online_order_cannot_claim_a_customer_id(monkeypatch):
    monkeypatch.setattr("app.modules.orders.service.is_weekly_holiday", lambda *_: False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            service = OrderService(db)
            service.settings_service.get_menu_checkout_settings = AsyncMock(return_value=SimpleNamespace(
                ordering_enabled=True, instapay_enabled=True, wallet_enabled=True,
            ))
            service._validate_order_items = AsyncMock(side_effect=AssertionError("claimed account reached pricing"))
            data = OrderCreate(
                order_type=OrderType.TAKEAWAY, source=OrderSource.ONLINE, customer_id=123,
                items=[OrderItemCreate(product_id=1, quantity=1, unit_price=Decimal(100))],
            )
            with pytest.raises(ValidationError, match="بيانات الحساب"):
                await service.create_order(data)
            service._validate_order_items.assert_not_called()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_submitted_price_cannot_overwrite_catalog_price(monkeypatch):
    product = SimpleNamespace(
        id=1, product_name="وجبة", is_available=True,
        category=SimpleNamespace(is_active=True, is_deleted=False),
        variants=[SimpleNamespace(price=Decimal(100), is_deleted=False)],
    )
    monkeypatch.setattr(ProductService, "get_products_by_ids", AsyncMock(return_value=[product]))
    service = OrderService(db=object(), pricing_service=object(), offer_service=object())
    with pytest.raises(ValidationError, match="سعر الصنف.*اتغير"):
        await service._validate_order_items([OrderItemCreate(product_id=1, quantity=1, unit_price=Decimal(1))])
