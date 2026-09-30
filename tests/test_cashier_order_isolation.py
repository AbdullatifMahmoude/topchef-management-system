from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.business_calendar import get_current_business_date
from app.core.database import Base
from app.core.enums import OrderSource, OrderType, PaymentMethod, UserRole
from app.core.exceptions import AuthorizationError
from app.modules.orders.models import Order
from app.modules.orders.repository import OrderRepository
from app.modules.report.service import get_report_summary
from app.modules.orders.router import (
    get_order_detail,
    update_order,
    update_order_status,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [get_order_detail, update_order, update_order_status])
async def test_cashier_cannot_access_another_cashiers_order(handler):
    service = SimpleNamespace(
        get_order=AsyncMock(return_value=SimpleNamespace(
            order_source=OrderSource.CASHIER, created_by_user_id=8,
        )),
        update_order=AsyncMock(),
        update_order_status=AsyncMock(),
    )
    kwargs = {"order_id": 1, "service": service, "current_user": SimpleNamespace(id=7, role=UserRole.CASHIER)}
    if handler is not get_order_detail:
        kwargs["update_data"] = SimpleNamespace()

    with pytest.raises(AuthorizationError):
        await handler(**kwargs)

    service.update_order.assert_not_awaited()
    service.update_order_status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,source,owner", [
    (UserRole.CASHIER, OrderSource.CASHIER, 7),
    (UserRole.CASHIER, OrderSource.ONLINE, None),
    (UserRole.ADMIN, OrderSource.CASHIER, 8),
])
async def test_own_and_shared_orders_remain_accessible(role, source, owner):
    order = SimpleNamespace(order_source=source, created_by_user_id=owner)
    service = SimpleNamespace(get_order=AsyncMock(return_value=order))

    result = await get_order_detail(1, service, SimpleNamespace(id=7, role=role))

    assert result is order


@pytest.mark.asyncio
async def test_cashier_order_lists_only_include_own_cashier_orders():
    import app.main  # noqa: F401 - register ORM tables

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            for number, source, owner, method, amount in [
                ("OWN", OrderSource.CASHIER, 7, PaymentMethod.CASH, 100),
                ("OTHER", OrderSource.CASHIER, 8, PaymentMethod.CASH, 400),
                ("ONLINE", OrderSource.ONLINE, None, PaymentMethod.WALLET, 200),
                ("DIGITAL", OrderSource.ONLINE, None, PaymentMethod.INSTAPAY, 300),
            ]:
                db.add(Order(
                    order_number=number, order_date=get_current_business_date(),
                    order_source=source, order_type=OrderType.HALL,
                    created_by_user_id=owner, payment_method=method, total_amount=amount,
                ))
            await db.commit()

        async with sessions() as db:
            repository = OrderRepository(db)
            count, page = await repository.list_orders_paginated(
                source=OrderSource.CASHIER, cashier_id=7,
            )
            dashboard = await repository.list_dashboard_orders(
                source=OrderSource.CASHIER, cashier_id=7,
            )
            shared_count, shared_page = await repository.list_orders_paginated(
                source=OrderSource.ONLINE, cashier_id=7,
            )
            summary = await get_report_summary(
                db, get_current_business_date(), get_current_business_date(),
            )

        assert count == 1
        assert [order.order_number for order in page] == ["OWN"]
        assert [order.order_number for order in dashboard] == ["OWN"]

        assert shared_count == 2
        assert {order.order_number for order in shared_page} == {"ONLINE", "DIGITAL"}
        assert summary.total_revenue == 1000
        assert summary.net_profit == 1000
    finally:
        await engine.dispose()
