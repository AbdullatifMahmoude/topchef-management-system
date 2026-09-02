from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.enums import OrderStatus, OrderType, PaymentMethod
from app.modules.shifts.service import ShiftsService


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_active_night_shift_keeps_orders_after_business_day_cutoff():
    egypt_tz = timezone(timedelta(hours=3))
    now_local = datetime.now(egypt_tz).replace(tzinfo=None)
    # Keep the fixture in the past so the 06:00 order is always before now,
    # regardless of the wall-clock time at which the test runs.
    target_date = now_local.date() - timedelta(days=2)
    start_local = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).replace(
        hour=0, minute=30
    )
    order_local = start_local.replace(hour=6)
    shift = SimpleNamespace(
        id=1,
        user_id=7,
        user=SimpleNamespace(full_name="Night Cashier", username="night"),
        start_time=start_local - timedelta(hours=3),
        end_time=None,
        target_date=target_date,
        opening_cash=0,
        actual_closing_cash=None,
        closing_note=None,
    )
    order = SimpleNamespace(
        created_by_user_id=7,
        created_at=order_local,
        order_status=OrderStatus.COMPLETED,
        total_amount=100,
        delivery_fee=0,
        discount_amount=0,
        payment_method=PaymentMethod.CASH,
        order_type=OrderType.HALL,
    )
    db = AsyncMock()
    db.execute.side_effect = [_Result([shift]), _Result([order]), _Result([])]

    report = await ShiftsService(db).get_shifts_report(target_date)

    assert report[0]["total_orders"] == 1
    assert report[0]["total_sales"] == 100
    assert report[0]["duration_minutes"] > 270


@pytest.mark.asyncio
async def test_end_shift_finds_open_shift_without_target_date_restriction():
    shift = SimpleNamespace(end_time=None)
    db = AsyncMock()
    db.execute.return_value = _Result([shift])

    await ShiftsService(db).end_shift(user_id=7)

    assert shift.end_time is not None
    db.commit.assert_awaited_once()
