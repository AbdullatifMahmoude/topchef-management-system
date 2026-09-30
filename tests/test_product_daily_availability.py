from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.business_calendar import (
    BUSINESS_DAY_START_HOUR, EGYPT_TZ, get_current_business_date, is_weekly_holiday,
)
from app.core.database import Base
from app.core.enums import ProductType, UserRole
from app.core.exceptions import ValidationError
from app.modules.infrastructure.middlewares.role_guard import Capability, _has_capability
from app.modules.menu.models import Category, Product, Variant
from app.modules.menu.service import ProductService, next_daily_availability_deadline
from app.modules.orders.schemas import OrderItemCreate
from app.modules.orders.service import OrderService


def test_only_cashier_and_admin_can_change_daily_availability():
    assert _has_capability(UserRole.CASHIER, Capability.TOGGLE_DAILY_PRODUCT)
    assert _has_capability(UserRole.ADMIN, Capability.TOGGLE_DAILY_PRODUCT)
    assert not _has_capability(UserRole.DELIVERY, Capability.TOGGLE_DAILY_PRODUCT)
    assert not _has_capability(UserRole.CASHIER, Capability.MANAGE_MENU)


def test_deadline_uses_restaurant_business_day_and_skips_friday():
    before_cutoff = datetime(2026, 10, 1, 6, 30, tzinfo=EGYPT_TZ)
    after_cutoff = datetime(2026, 10, 1, 8, 0, tzinfo=EGYPT_TZ)
    assert next_daily_availability_deadline(before_cutoff) == datetime(2026, 10, 1, 4, 0)
    assert next_daily_availability_deadline(after_cutoff) == datetime(2026, 10, 3, 4, 0)


@pytest.mark.asyncio
async def test_daily_toggle_keeps_product_visible_blocks_checkout_and_expires(monkeypatch):
    import app.main  # noqa: F401 - register related ORM tables

    monkeypatch.setattr("app.core.events.order_events_manager.emit", AsyncMock())
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            product = Product(
                category=Category(cat_name="Daily test"), product_name="Test product",
                product_type=ProductType.SIMPLE, is_available=True,
                variants=[Variant(name="Normal", price=Decimal("50.00"))],
            )
            db.add(product)
            await db.commit()
            product_id = product.id

        async with sessions() as db:
            service = ProductService(db)
            paused = await service.toggle_daily_availability(product_id, actor_id=7)
            assert paused.is_available is True
            assert paused.temporary_unavailable_until is not None
            expected_day = get_current_business_date() + timedelta(days=1)
            while is_weekly_holiday(expected_day):
                expected_day += timedelta(days=1)
            expected = datetime.combine(expected_day, datetime.min.time()).replace(
                hour=BUSINESS_DAY_START_HOUR, tzinfo=EGYPT_TZ,
            ).astimezone(UTC).replace(tzinfo=None)
            assert paused.temporary_unavailable_until == expected
            assert [p.id for p in await service.list_products(only_active=True)] == [product_id]

            order_service = OrderService(db, pricing_service=object(), offer_service=object())
            item = OrderItemCreate(product_id=product_id, quantity=1, unit_price=Decimal("50.00"))
            with pytest.raises(ValidationError, match="لباقي يوم العمل"):
                await order_service._validate_order_items([item])

            restored = await service.toggle_daily_availability(product_id, actor_id=7)
            assert restored.temporary_unavailable_until is None
            await order_service._validate_order_items([item])

            product = await service.repo.get_by_id(product_id)
            product.temporary_unavailable_until = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            assert not product.is_temporarily_unavailable
            product.is_available = False
            with pytest.raises(ValidationError, match="بشكل دائم"):
                await service.toggle_daily_availability(product_id, actor_id=7)
    finally:
        await engine.dispose()
