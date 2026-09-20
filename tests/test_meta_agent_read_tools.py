from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.enums import OrderStatus
from app.modules.meta_agent.service import get_available_menu, get_owned_order_status


class FakeScalars:
    def __init__(self, items):
        self.items = items

    def unique(self):
        return self

    def all(self):
        return self.items

    def __iter__(self):
        return iter(self.items)


class FakeResult:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return FakeScalars(self.items)

    def all(self):
        return self.items


class FakeSession:
    def __init__(self, *results):
        self.results = iter(results)
        self.execute_count = 0

    async def execute(self, _statement):
        self.execute_count += 1
        return FakeResult(next(self.results))


@pytest.mark.asyncio
async def test_menu_excludes_deleted_variants_and_products_without_prices():
    available = SimpleNamespace(
        product_id=1,
        product_name="وجبة توب شيف",
        description="وجبة كاملة",
        cat_name="الوجبات",
        variant_id=11,
        variant_name="عادي",
        price=Decimal("125.00"),
    )

    response = await get_available_menu(FakeSession([available]))

    assert [product.name for product in response.products] == ["وجبة توب شيف"]
    assert [variant.name for variant in response.products[0].variants] == ["عادي"]
    assert response.products[0].variants[0].price == Decimal("125.00")


@pytest.mark.asyncio
async def test_order_status_matches_equivalent_egyptian_phone_and_returns_history():
    updated_at = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    order = SimpleNamespace(
        id=7,
        order_number="123",
        customer_phone="+20 10 0000 0000",
        order_status=OrderStatus.CONFIRMED,
        updated_at=updated_at,
    )
    history = SimpleNamespace(
        status=OrderStatus.NEW,
        changed_at=datetime(2026, 9, 20, 11, 0, tzinfo=UTC),
    )

    response = await get_owned_order_status(
        FakeSession([order], [history]),
        order_number="#123",
        customer_phone="01000000000",
    )

    assert response is not None
    assert response.order_number == "123"
    assert response.status == "confirmed"
    assert response.status_label == "تم التأكيد"
    assert response.history[0].status == "new"


@pytest.mark.asyncio
async def test_order_status_hides_order_when_phone_does_not_match():
    order = SimpleNamespace(
        id=7,
        order_number="123",
        customer_phone="01000000000",
        order_status=OrderStatus.CONFIRMED,
        updated_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
    )
    session = FakeSession([order])

    response = await get_owned_order_status(
        session,
        order_number="123",
        customer_phone="01111111111",
    )

    assert response is None
    assert session.execute_count == 1


@pytest.mark.asyncio
async def test_order_status_rejects_invalid_phone_without_querying_database():
    session = FakeSession()

    response = await get_owned_order_status(
        session,
        order_number="123",
        customer_phone="123",
    )

    assert response is None
    assert session.execute_count == 0
