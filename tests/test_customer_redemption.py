from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - register all ORM tables
from app.core.database import Base
from app.core.enums import OrderSource, OrderStatus, OrderType, ProductType
from app.core.exceptions import AuthenticationError, ValidationError
from app.modules.auth.dependencies import get_optional_user
from app.modules.customer.loyalty import customer_points_balance
from app.modules.customer.models import Customer, CustomerDevice, CustomerPointLedger
from app.modules.menu.models import Category, Product, Variant
from app.modules.orders.dependencies import get_order_service
from app.modules.orders.models import Order
from app.modules.orders.router import router as order_router
from app.modules.orders.schemas import (
    OrderCreate,
    OrderItemCreate,
    OrderResponse,
    OrderUpdate,
    OrderUpdateFull,
)
from app.modules.orders.service import OrderService
from app.modules.settings.schemas import LoyaltySettingsUpdate
from app.modules.settings.service import SettingsService


def test_guest_cannot_submit_points_reward():
    isolated_app = FastAPI()
    isolated_app.include_router(order_router)
    fake_service = SimpleNamespace(create_order=AsyncMock())
    isolated_app.dependency_overrides[get_order_service] = lambda: fake_service
    isolated_app.dependency_overrides[get_optional_user] = lambda: None

    @isolated_app.exception_handler(AuthenticationError)
    async def auth_error(_request, _exc):
        return JSONResponse(status_code=401, content={"detail": "login required"})

    response = TestClient(isolated_app).post("/orders/", json={
        "order_type": "takeaway", "items": [{"product_id": 1, "quantity": 1, "unit_price": "100"}],
        "loyalty_rule_id": "11111111-1111-4111-8111-111111111111",
        "loyalty_expected_points": 100, "loyalty_expected_value": "10",
    })
    assert response.status_code == 401
    fake_service.create_order.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("reward_type,points_cost,discount,expected_subtotal,expected_total", [
    ("fixed_discount", 150, Decimal(10), Decimal(100), Decimal(90)),
    ("free_product", 150, Decimal(40), Decimal(140), Decimal(100)),
])
async def test_redemption_reserves_consumes_and_returns_points(
    monkeypatch, reward_type, points_cost, discount, expected_subtotal, expected_total,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.modules.orders.service.is_weekly_holiday", lambda *_: False)
    monkeypatch.setattr("app.modules.orders.service.order_events_manager.emit", AsyncMock())
    try:
        async with session_factory() as db:
            async with db.begin():
                category = Category(cat_name="Test", is_active=True, is_deleted=False)
                db.add(category)
                await db.flush()
                meal = Product(cat_id=category.id, product_name="Meal", product_type=ProductType.SIMPLE,
                               is_available=True, is_deleted=False)
                gift = Product(cat_id=category.id, product_name="Gift", product_type=ProductType.SIMPLE,
                               is_available=True, is_deleted=False)
                db.add_all([meal, gift])
                await db.flush()
                meal_variant = Variant(product_id=meal.id, name="Regular", price=Decimal(100))
                gift_variant = Variant(product_id=gift.id, name="Small", price=Decimal(40))
                db.add_all([meal_variant, gift_variant])
                customer = Customer(name="Test", phone_number="01000000009", pin_hash="hash",
                                    account_activated_at=datetime.now(UTC).replace(tzinfo=None))
                db.add(customer)
                await db.flush()
                device = CustomerDevice(id="device-1", customer_id=customer.id,
                                        refresh_token_hash="test-hash", device_name="test",
                                        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1))
                earned_order = Order(order_number="earned", customer_id=customer.id,
                                     customer_phone=customer.phone_number, order_type=OrderType.TAKEAWAY,
                                     order_source=OrderSource.ONLINE, order_status=OrderStatus.CONFIRMED,
                                     subtotal=Decimal(300), discount_amount=Decimal(0), total_amount=Decimal(300))
                db.add_all([device, earned_order])
                await db.flush()
                db.add(CustomerPointLedger(customer_id=customer.id, order_id=earned_order.id,
                                           points=200, eligible_amount=Decimal(300), rules_snapshot="{}"))
                rule = {"reward_type": reward_type, "points_required": points_cost}
                if reward_type == "fixed_discount":
                    rule["discount_amount"] = str(discount)
                else:
                    rule.update(product_id=gift.id, variant_id=gift_variant.id)
                config = await SettingsService(db).update_loyalty_settings(LoyaltySettingsUpdate(
                    redemption_enabled=True, redemption_rules=[rule],
                ))
                rule_id = config.redemption_rules[0].id
                customer_id = customer.id
                meal_id = meal.id
            service = OrderService(db, notification_service=AsyncMock())
            service.settings_service.get_menu_checkout_settings = AsyncMock(return_value=SimpleNamespace(
                ordering_enabled=True, instapay_enabled=True, wallet_enabled=True,
            ))
            payload = {"customer_id": customer_id, "device_id": "device-1"}
            order_data = OrderCreate(
                customer_name="Test", customer_phone="01000000009", order_type=OrderType.TAKEAWAY,
                source=OrderSource.ONLINE, items=[OrderItemCreate(product_id=meal_id, quantity=1,
                                                                   unit_price=Decimal(100))],
                loyalty_rule_id=rule_id, loyalty_expected_points=points_cost,
                loyalty_expected_value=discount, idempotency_key=f"reward-{reward_type}",
            )
            order = await service.create_order(order_data, redeeming_customer=payload)
            assert order.subtotal == expected_subtotal
            assert order.loyalty_discount_amount == discount
            assert order.total_amount == expected_total
            assert order.loyalty_status == "reserved"
            exposed = OrderResponse.model_validate(order)
            assert exposed.loyalty_discount_amount == discount
            assert exposed.loyalty_points_spent == points_cost
            assert exposed.loyalty_reward_type == reward_type
            assert len(order.items) == (2 if reward_type == "free_product" else 1)
            assert await customer_points_balance(db, customer_id) == 200 - points_cost

            duplicate = await service.create_order(order_data, redeeming_customer=payload)
            assert duplicate.id == order.id
            assert await customer_points_balance(db, customer_id) == 200 - points_cost
            with pytest.raises(ValidationError, match="مفتاح تكرار الطلب"):
                await service.create_order(
                    order_data.model_copy(update={"customer_phone": "01000000007"}),
                    redeeming_customer=payload,
                )
            with pytest.raises(ValidationError, match="رصيد النقاط غير كاف"):
                await service.create_order(
                    order_data.model_copy(update={"idempotency_key": f"second-{reward_type}"}),
                    redeeming_customer=payload,
                )

            await service.update_order_status(order.id, OrderUpdate(order_status=OrderStatus.CONFIRMED))
            assert await customer_points_balance(db, customer_id) == 200 - points_cost
            edited = await service.update_order(order.id, OrderUpdateFull(items=[
                OrderItemCreate(product_id=meal_id, quantity=2 if reward_type == "fixed_discount" else 1,
                                unit_price=Decimal(100)),
                *([OrderItemCreate(product_id=gift.id, quantity=1, unit_price=Decimal(40))]
                  if reward_type == "free_product" else []),
            ]))
            assert edited.loyalty_status == "consumed"
            assert edited.loyalty_discount_amount == discount
            assert await customer_points_balance(db, customer_id) == 200 - points_cost
            if reward_type == "free_product":
                without_gift = await service.update_order(order.id, OrderUpdateFull(items=[
                    OrderItemCreate(product_id=meal_id, quantity=1, unit_price=Decimal(100)),
                ]))
                assert without_gift.loyalty_status == "reversed"
                assert without_gift.loyalty_discount_amount == 0
                assert without_gift.total_amount == 100
                assert await customer_points_balance(db, customer_id) == 200
            await service.update_order_status(order.id, OrderUpdate(order_status=OrderStatus.CANCELLED))
            assert await customer_points_balance(db, customer_id) == 200
            with pytest.raises(ValidationError, match="مكافأة النقاط اتغيرت"):
                await service.create_order(
                    order_data.model_copy(update={
                        "idempotency_key": f"stale-{reward_type}",
                        "loyalty_expected_value": discount + Decimal(1),
                    }),
                    redeeming_customer=payload,
                )
            pending = await service.create_order(
                order_data.model_copy(update={"idempotency_key": f"pending-{reward_type}"}),
                redeeming_customer=payload,
            )
            assert await customer_points_balance(db, customer_id) == 200 - points_cost
            await service.update_order_status(pending.id, OrderUpdate(order_status=OrderStatus.CANCELLED))
            assert await customer_points_balance(db, customer_id) == 200
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redemption_rejects_wrong_phone_and_missing_device():
    from app.modules.customer.loyalty import select_redemption

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db, db.begin():
            customer = Customer(name="Test", phone_number="01000000008", pin_hash="hash",
                                account_activated_at=datetime.now(UTC).replace(tzinfo=None))
            db.add(customer)
            await db.flush()
            with pytest.raises(AuthenticationError):
                await select_redemption(db, "missing", {"customer_id": customer.id}, "01000000008")
            with pytest.raises(AuthenticationError):
                await select_redemption(db, "missing", {"customer_id": customer.id}, "01000000007")
    finally:
        await engine.dispose()
