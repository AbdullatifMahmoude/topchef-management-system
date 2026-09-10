from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.menu import models as _menu_models  # noqa: F401 - register ORM relationships
from app.core.business_calendar import EGYPT_TZ
from app.core.enums import OrderStatus, OrderType, PaymentMethod
from app.modules.orders.router import get_rider_stats


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return _Scalars(self.rows)


@pytest.mark.asyncio
async def test_rider_stats_calculates_active_order_age_with_cairo_time():
    created_at = datetime.now(EGYPT_TZ).replace(tzinfo=None) - timedelta(minutes=10)
    order = SimpleNamespace(
        id=1,
        order_number="T1-0001",
        order_status=OrderStatus.CONFIRMED,
        order_type=OrderType.DELIVERY,
        delivery_person_id=None,
        delivery_person_name=None,
        total_amount=100,
        delivery_fee=10,
        payment_method=PaymentMethod.CASH,
        customer_name="Customer",
        customer_phone="01000000000",
        customer_address="Address",
        created_at=created_at,
    )
    db = AsyncMock()
    db.execute.side_effect = [_Result([]), _Result([order])]

    result = await get_rider_stats(db=db, current_user=SimpleNamespace())

    assert result["business_day_start"].endswith("T07:00:00")
    assert len(result["orders"]) == 1
    assert result["orders"][0]["age_minutes"] >= 9


@pytest.mark.asyncio
async def test_rider_stats_separates_gross_collection_fee_and_restaurant_remittance():
    rider = SimpleNamespace(
        id=7,
        full_name="Rider",
        username="rider",
        phone="01000000000",
    )
    orders = [
        SimpleNamespace(
            id=1,
            order_number="T1-0001",
            order_status=OrderStatus.CONFIRMED,
            order_type=OrderType.DELIVERY,
            delivery_person_id=7,
            delivery_person_name="Rider",
            total_amount=120,
            delivery_fee=20,
            payment_method=PaymentMethod.CASH,
            customer_name="Customer",
            customer_phone="01000000001",
            customer_address="Address",
            created_at=datetime.now(EGYPT_TZ).replace(tzinfo=None),
        ),
        SimpleNamespace(
            id=2,
            order_number="T1-0002",
            order_status=OrderStatus.DELIVERED,
            order_type=OrderType.DELIVERY,
            delivery_person_id=7,
            delivery_person_name="Rider",
            total_amount=80,
            delivery_fee=10,
            payment_method=PaymentMethod.INSTAPAY,
            customer_name="Customer",
            customer_phone="01000000002",
            customer_address="Address",
            created_at=datetime.now(EGYPT_TZ).replace(tzinfo=None),
        ),
        SimpleNamespace(
            id=3,
            order_number="T1-0003",
            order_status=OrderStatus.CANCELLED,
            order_type=OrderType.DELIVERY,
            delivery_person_id=7,
            delivery_person_name="Rider",
            total_amount=500,
            delivery_fee=50,
            payment_method=PaymentMethod.CASH,
            customer_name="Customer",
            customer_phone="01000000003",
            customer_address="Address",
            created_at=datetime.now(EGYPT_TZ).replace(tzinfo=None),
        ),
    ]
    db = AsyncMock()
    db.execute.side_effect = [_Result([rider]), _Result(orders)]

    result = await get_rider_stats(db=db, current_user=SimpleNamespace())

    stats = result["stats"][0]
    assert stats["cash_amount"] == 120
    assert stats["digital_amount"] == 80
    assert stats["delivery_fees"] == 30
    assert stats["order_value"] == 170
    assert stats["total_orders"] == 2
    assert result["summary"]["cash_to_collect"] == 120
