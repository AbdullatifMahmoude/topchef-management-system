from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - register ORM models
from app.core.database import Base
from app.core.enums import OrderSource, OrderStatus, OrderType
from app.modules.customer.loyalty import (
    award_order_points,
    customer_points_balance,
    recalculate_order_points,
    reverse_order_points,
)
from app.modules.customer.models import Customer, CustomerPointLedger
from app.modules.orders.models import Order
from app.modules.orders.schemas import OrderUpdate
from app.modules.orders.service import OrderService
from app.modules.settings.models import AppSetting
from app.modules.settings.schemas import LoyaltySettingsUpdate
from app.modules.settings.service import SettingsService


def rules(*, enabled=True):
    return LoyaltySettingsUpdate.model_validate({
        "enabled": enabled,
        "minimum_order_amount": "100",
        "max_points_per_order": 1000,
        "tiers": [
            {"from_amount": "0", "step_amount": "100", "points_per_step": 10},
            {"from_amount": "100", "step_amount": "100", "points_per_step": 15},
        ],
    })


@pytest.mark.parametrize("bad", [
    {"enabled": True, "tiers": []},
    {"enabled": True, "tiers": [{"from_amount": 100, "step_amount": 100, "points_per_step": 10}]},
    {"enabled": True, "tiers": [
        {"from_amount": 0, "step_amount": 100, "points_per_step": 10},
        {"from_amount": 150, "step_amount": 100, "points_per_step": 15},
    ]},
    {"redemption_enabled": True, "redemption_rules": []},
    {"redemption_enabled": True, "redemption_rules": [
        {"id": "11111111-1111-4111-8111-111111111111", "points_required": 100, "discount_amount": "10"},
        {"id": "11111111-1111-4111-8111-111111111111", "points_required": 200, "discount_amount": "20"},
    ]},
    {"redemption_enabled": True, "redemption_rules": [
        {"reward_type": "free_product", "points_required": 200, "product_id": 1},
    ]},
])
def test_invalid_rules_cannot_be_enabled(bad):
    with pytest.raises(ValueError):
        LoyaltySettingsUpdate.model_validate(bad)


@pytest.mark.asyncio
async def test_points_follow_confirmed_order_snapshot_and_reverse_on_cancel():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(
            sync, tables=[Customer.__table__, Order.__table__, AppSetting.__table__, CustomerPointLedger.__table__],
        ))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db, db.begin():
            customer = Customer(name="عميل", phone_number="01000000001", pin_hash="hash",
                                account_activated_at=datetime.now(UTC).replace(tzinfo=None))
            guest = Customer(name="ضيف", phone_number="01000000002")
            db.add_all([customer, guest])
            await db.flush()
            order = Order(order_number="1", customer_id=customer.id, customer_phone=customer.phone_number,
                          order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                          order_status=OrderStatus.CONFIRMED, subtotal=Decimal(250),
                          discount_amount=Decimal(0), total_amount=Decimal(250))
            guest_order = Order(order_number="2", customer_id=guest.id, customer_phone=guest.phone_number,
                                order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                                order_status=OrderStatus.CONFIRMED, subtotal=Decimal(250),
                                discount_amount=Decimal(0), total_amount=Decimal(250))
            db.add_all([order, guest_order])
            await db.flush()

            assert await award_order_points(db, order) is False  # no admin rules yet
            await SettingsService(db).update_loyalty_settings(rules())
            assert await award_order_points(db, guest_order) is False
            assert await award_order_points(db, order) is True
            assert await award_order_points(db, order) is False
            assert await customer_points_balance(db, customer.id) == 25

            await SettingsService(db).update_loyalty_settings(LoyaltySettingsUpdate(enabled=False))
            order.subtotal = Decimal(350)
            order.total_amount = Decimal(350)
            assert await recalculate_order_points(db, order) is True
            assert await customer_points_balance(db, customer.id) == 40

            assert await reverse_order_points(db, order.id) is True
            assert await reverse_order_points(db, order.id) is False
            assert await customer_points_balance(db, customer.id) == 0

            configured = await SettingsService(db).update_loyalty_settings(LoyaltySettingsUpdate(
                redemption_enabled=True,
                redemption_rules=[{"points_required": 100, "discount_amount": "10"}],
            ))
            assert configured.redemption_active is True
            assert configured.redemption_rules[0].discount_amount == Decimal(10)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_zero_point_award_can_grow_after_confirmed_order_edit():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(
            sync, tables=[Customer.__table__, Order.__table__, AppSetting.__table__, CustomerPointLedger.__table__],
        ))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db, db.begin():
            customer = Customer(name="عميل", phone_number="01000000003", pin_hash="hash",
                                account_activated_at=datetime.now(UTC).replace(tzinfo=None))
            db.add(customer)
            await db.flush()
            order = Order(order_number="3", customer_id=customer.id, customer_phone=customer.phone_number,
                          order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                          order_status=OrderStatus.CONFIRMED, subtotal=Decimal(50),
                          discount_amount=Decimal(0), total_amount=Decimal(50))
            db.add(order)
            await db.flush()
            await SettingsService(db).update_loyalty_settings(rules())
            assert await award_order_points(db, order) is True
            assert await customer_points_balance(db, customer.id) == 0
            order.subtotal = Decimal(250)
            order.discount_amount = Decimal(50)
            assert await recalculate_order_points(db, order) is True
            assert await customer_points_balance(db, customer.id) == 25
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_order_status_journey_awards_once_then_reverses(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.modules.orders.service.order_events_manager.emit", AsyncMock())
    try:
        async with session_factory() as db:
            async with db.begin():
                customer = Customer(name="عميل", phone_number="01000000004", pin_hash="hash",
                                    account_activated_at=datetime.now(UTC).replace(tzinfo=None))
                db.add(customer)
                await db.flush()
                order = Order(order_number="4", customer_id=customer.id, customer_phone=customer.phone_number,
                              order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                              order_status=OrderStatus.NEW, subtotal=Decimal(250),
                              discount_amount=Decimal(0), total_amount=Decimal(250))
                db.add(order)
                await db.flush()
                await SettingsService(db).update_loyalty_settings(rules())
                order_id, customer_id = order.id, customer.id
            service = OrderService(db, notification_service=AsyncMock())
            await service.update_order_status(order_id, OrderUpdate(order_status=OrderStatus.CONFIRMED))
            assert await customer_points_balance(db, customer_id) == 25
            await service.update_order_status(order_id, OrderUpdate(order_status=OrderStatus.CONFIRMED))
            assert await customer_points_balance(db, customer_id) == 25
            await service.update_order_status(order_id, OrderUpdate(order_status=OrderStatus.CANCELLED))
            assert await customer_points_balance(db, customer_id) == 0
    finally:
        await engine.dispose()
