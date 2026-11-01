import importlib.util
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - register ORM tables
from app.core.database import Base
from app.core.enums import OrderSource, OrderStatus, OrderType
from app.core.exceptions import ValidationError
from app.modules.customer.loyalty import (
    customer_points_balance,
    points_month_bounds,
    select_redemption,
)
from app.modules.customer.models import (
    Customer,
    CustomerDevice,
    CustomerNotification,
    CustomerPointLedger,
)
from app.modules.orders.models import Order
from app.modules.orders.notifications import AccountOrderNotifications
from app.modules.orders.schemas import OrderUpdate
from app.modules.orders.service import OrderService
from app.modules.settings.schemas import LoyaltySettingsUpdate
from app.modules.settings.service import SettingsService


def naive_time(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build an intentional naive timestamp for the legacy UTC/Cairo database columns."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC).replace(tzinfo=None)


def test_cairo_calendar_month_boundary_and_seasonal_offset():
    september_end = datetime(2026, 9, 30, 20, 59, tzinfo=UTC)
    october_start = datetime(2026, 9, 30, 21, 0, tzinfo=UTC)
    assert points_month_bounds(september_end)[2].month == 9
    assert points_month_bounds(october_start)[2].month == 10
    assert points_month_bounds(october_start)[0] == october_start
    assert points_month_bounds(datetime(2026, 7, 10, tzinfo=UTC))[2].utcoffset().total_seconds() == 3 * 3600
    assert points_month_bounds(datetime(2026, 12, 10, tzinfo=UTC))[2].utcoffset().total_seconds() == 2 * 3600


def test_reservation_migration_keeps_order_created_at_unchanged(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "loyalty_monthly_reservation", Path("alembic/versions/a93026_loyalty_monthly_reservation.py"),
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE orders (id INTEGER PRIMARY KEY, created_at DATETIME)")
            connection.exec_driver_sql("INSERT INTO orders VALUES (1, '2026-09-30 23:59:00')")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert "loyalty_reserved_at" in {column["name"] for column in inspect(connection).get_columns("orders")}
            assert connection.exec_driver_sql("SELECT created_at FROM orders WHERE id=1").scalar() == "2026-09-30 23:59:00"
            migration.downgrade()
            assert "loyalty_reserved_at" not in {column["name"] for column in inspect(connection).get_columns("orders")}
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_new_month_expires_old_points_but_preserves_old_order_reservation():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            customer = Customer(name="Monthly", phone_number="01000000011")
            db.add(customer)
            await db.flush()
            old_order = Order(order_number="old", customer_id=customer.id, customer_phone=customer.phone_number,
                              order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                              order_status=OrderStatus.NEW, subtotal=Decimal(100), total_amount=Decimal(100),
                              loyalty_points_spent=150, loyalty_status="reserved",
                              loyalty_reserved_at=naive_time(2026, 9, 30, 20, 59),
                              created_at=naive_time(2026, 9, 30, 23, 59))
            new_order = Order(order_number="new", customer_id=customer.id, customer_phone=customer.phone_number,
                              order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                              order_status=OrderStatus.NEW, subtotal=Decimal(100), total_amount=Decimal(100),
                              loyalty_points_spent=25, loyalty_status="reserved",
                              loyalty_reserved_at=naive_time(2026, 9, 30, 21, 2),
                              created_at=naive_time(2026, 10, 1, 0, 2))
            db.add_all([old_order, new_order])
            await db.flush()
            db.add_all([
                CustomerPointLedger(customer_id=customer.id, order_id=old_order.id, points=200,
                                    eligible_amount=Decimal(200), rules_snapshot="{}",
                                    created_at=naive_time(2026, 9, 30, 20, 58)),
                CustomerPointLedger(customer_id=customer.id, order_id=new_order.id, points=50,
                                    eligible_amount=Decimal(100), rules_snapshot="{}",
                                    created_at=naive_time(2026, 9, 30, 21, 1)),
            ])
            await db.flush()
            assert await customer_points_balance(db, customer.id,
                                                 now=datetime(2026, 9, 30, 20, 59, tzinfo=UTC)) == 50
            assert await customer_points_balance(db, customer.id,
                                                 now=datetime(2026, 9, 30, 21, 3, tzinfo=UTC)) == 25
            old_order.loyalty_status = "reversed"
            await db.flush()
            assert await customer_points_balance(db, customer.id,
                                                 now=datetime(2026, 9, 30, 21, 3, tzinfo=UTC)) == 25
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_last_month_points_cannot_fund_a_new_reward():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            customer = Customer(name="Monthly", phone_number="01000000013", pin_hash="hash",
                                account_activated_at=datetime.now(UTC).replace(tzinfo=None))
            db.add(customer)
            await db.flush()
            device = CustomerDevice(id="monthly-device", customer_id=customer.id, refresh_token_hash="monthly-hash",
                                    expires_at=(datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None))
            earned_order = Order(order_number="previous-month", customer_id=customer.id,
                                 customer_phone=customer.phone_number, order_type=OrderType.TAKEAWAY,
                                 order_source=OrderSource.ONLINE, order_status=OrderStatus.CONFIRMED,
                                 subtotal=Decimal(100), total_amount=Decimal(100))
            db.add_all([device, earned_order])
            await db.flush()
            previous_month = points_month_bounds()[0] - timedelta(minutes=1)
            db.add(CustomerPointLedger(customer_id=customer.id, order_id=earned_order.id, points=500,
                                       eligible_amount=Decimal(100), rules_snapshot="{}",
                                       created_at=previous_month.replace(tzinfo=None)))
            config = await SettingsService(db).update_loyalty_settings(LoyaltySettingsUpdate(
                redemption_enabled=True, redemption_rules=[{"points_required": 100, "discount_amount": "10"}],
            ))
            with pytest.raises(ValidationError, match="الشهر الحالي"):
                await select_redemption(db, str(config.redemption_rules[0].id),
                                        {"customer_id": customer.id, "device_id": device.id}, customer.phone_number)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_confirmation_persists_points_notification_with_monthly_balance(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr("app.modules.orders.service.order_events_manager.emit", AsyncMock())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            customer = Customer(name="Monthly", phone_number="01000000012", pin_hash="hash",
                                account_activated_at=datetime.now(UTC).replace(tzinfo=None))
            db.add(customer)
            await db.flush()
            order = Order(order_number="confirm", customer_id=customer.id, customer_phone=customer.phone_number,
                          order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                          order_status=OrderStatus.NEW, subtotal=Decimal(250), total_amount=Decimal(250))
            db.add(order)
            await db.flush()
            await SettingsService(db).update_loyalty_settings(LoyaltySettingsUpdate(
                enabled=True, tiers=[{"from_amount": 0, "step_amount": 100, "points_per_step": 10}],
            ))
            order_id = order.id
            await db.commit()

            await OrderService(db).update_order_status(order_id, OrderUpdate(order_status=OrderStatus.CONFIRMED))
            db.expire_all()
            notification = await db.scalar(select(CustomerNotification).where(
                CustomerNotification.order_id == order_id,
                CustomerNotification.event_key == f"order:{order_id}:status_changed:confirmed",
            ))
            assert notification is not None
            assert "كسبت 20 نقطة" in notification.message
            assert "بقى معاك 20 نقطة" in notification.message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_edit_of_expired_order_does_not_claim_new_month_points():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            customer = Customer(name="Monthly", phone_number="01000000014")
            db.add(customer)
            await db.flush()
            order = Order(order_number="expired", customer_id=customer.id, customer_phone=customer.phone_number,
                          order_type=OrderType.TAKEAWAY, order_source=OrderSource.ONLINE,
                          order_status=OrderStatus.CONFIRMED, subtotal=Decimal(100), total_amount=Decimal(100))
            db.add(order)
            await db.flush()
            old_award_at = (points_month_bounds()[0] - timedelta(minutes=1)).replace(tzinfo=None)
            db.add(CustomerPointLedger(customer_id=customer.id, order_id=order.id, points=20,
                                       eligible_amount=Decimal(100), rules_snapshot="{}", created_at=old_award_at))
            await db.flush()
            queued = await AccountOrderNotifications(db).enqueue({
                "id": order.id, "customer_id": customer.id, "order_number": order.order_number,
                "order_status": "confirmed", "updated_at": "2026-09-30T01:00:00",
            }, "updated")
            assert queued is True
            await db.flush()
            notification = await db.scalar(select(CustomerNotification).where(CustomerNotification.order_id == order.id))
            assert "تخص شهر سابق" in notification.message
            assert "كسبت" not in notification.message
    finally:
        await engine.dispose()
