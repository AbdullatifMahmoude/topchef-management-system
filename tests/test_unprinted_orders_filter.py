from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.business_calendar import get_current_business_date
from app.core.database import Base
from app.core.enums import OrderSource, OrderType, PaymentMethod, UserRole
from app.modules.orders import models, schemas
from app.modules.orders.repository import OrderRepository
from app.modules.orders.service import OrderService
from app.modules.orders.router import mark_order_printed


@pytest.mark.asyncio
async def test_order_is_printed_default_and_filter():
    import app.main  # noqa: F401 - register ORM tables

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            # Order 1: saved without printing (default is_printed=False)
            order1 = models.Order(
                order_number="UNPRINTED-1",
                order_date=get_current_business_date(),
                order_source=OrderSource.CASHIER,
                order_type=OrderType.HALL,
                created_by_user_id=7,
                payment_method=PaymentMethod.CASH,
                total_amount=100,
                is_printed=False,
            )
            # Order 2: saved with printing (is_printed=True)
            order2 = models.Order(
                order_number="PRINTED-1",
                order_date=get_current_business_date(),
                order_source=OrderSource.CASHIER,
                order_type=OrderType.TAKEAWAY,
                created_by_user_id=7,
                payment_method=PaymentMethod.CASH,
                total_amount=150,
                is_printed=True,
            )
            db.add_all([order1, order2])
            await db.commit()

        async with sessions() as db:
            repository = OrderRepository(db)

            # Query all orders
            total_all, all_orders = await repository.list_orders_paginated(
                source=OrderSource.CASHIER, cashier_id=7
            )
            assert total_all == 2
            assert {o.order_number for o in all_orders} == {"UNPRINTED-1", "PRINTED-1"}

            # Query unprinted orders only
            total_unprinted, unprinted_orders = await repository.list_orders_paginated(
                source=OrderSource.CASHIER, is_printed=False, cashier_id=7
            )
            assert total_unprinted == 1
            assert [o.order_number for o in unprinted_orders] == ["UNPRINTED-1"]
            assert unprinted_orders[0].is_printed is False

            # Query printed orders only
            total_printed, printed_orders = await repository.list_orders_paginated(
                source=OrderSource.CASHIER, is_printed=True, cashier_id=7
            )
            assert total_printed == 1
            assert [o.order_number for o in printed_orders] == ["PRINTED-1"]
            assert printed_orders[0].is_printed is True

            # Mark order1 as printed using service
            service = OrderService(db, repository, AsyncMock())
            updated = await service.mark_order_printed(order1.id)
            assert updated.is_printed is True

            # Now verify unprinted list is empty
            total_unprinted_after, unprinted_after = await repository.list_orders_paginated(
                source=OrderSource.CASHIER, is_printed=False, cashier_id=7
            )
            assert total_unprinted_after == 0
            assert len(unprinted_after) == 0

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_mark_order_printed_router_endpoint():
    mock_order = SimpleNamespace(id=42, order_source=OrderSource.CASHIER, created_by_user_id=7, is_printed=True)
    service = SimpleNamespace(
        get_order=AsyncMock(return_value=mock_order),
        mark_order_printed=AsyncMock(return_value=mock_order),
    )
    current_user = SimpleNamespace(id=7, role=UserRole.CASHIER)

    result = await mark_order_printed(42, service=service, current_user=current_user)
    assert result.is_printed is True
    service.mark_order_printed.assert_awaited_once_with(42)


def test_cashier_html_contains_unprinted_filter_button():
    html = Path("app/frontend/cashier/cashier.html").read_text(encoding="utf-8")
    assert "setAllOrdersFilter('unprinted', this)" in html
    assert "محفوظة بدون طباعة" in html


def test_cashier_js_handles_unprinted_filter_and_marking():
    js = Path("app/frontend/cashier/js/cashier.js").read_text(encoding="utf-8")
    assert 'if (allOrdersFilter === "unprinted")' in js
    assert '&is_printed=false' in js
    assert 'markOrderAsPrinted' in js
    assert 'غير مطبوع' in js
