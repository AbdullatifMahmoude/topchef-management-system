from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401
from app.core.database import Base
from app.core.enums import OrderSource, OrderStatus, OrderType, PaymentMethod, UserRole
from app.modules.orders.models import Order
from app.modules.report.service import get_activity_breakdown, get_report_orders
from app.modules.shifts.models import CashierShift
from app.modules.shifts.service import ShiftsService
from app.modules.users.models import User


def naive(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_winter_seven_am_boundary_preserves_shift_sales_and_report_hours():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            cashier = User(username="winter-test", phone="01099999999", hashed_password="x", role=UserRole.CASHIER)
            db.add(cashier)
            await db.flush()
            shift = CashierShift(user_id=cashier.id, target_date=date(2026, 10, 30),
                                 start_time=naive(2026, 10, 30, 18), end_time=naive(2026, 10, 31, 5),
                                 opening_cash=Decimal(300), cash_tracking_enabled=True)
            db.add(shift)
            for number, day, when, amount in [
                ("PRE", date(2026, 10, 30), naive(2026, 10, 31, 7, 59), 100),
                ("POST", date(2026, 10, 31), naive(2026, 10, 31, 8), 200),
            ]:
                db.add(Order(order_number=number, order_date=day, created_at=when,
                             created_by_user_id=cashier.id, order_source=OrderSource.CASHIER,
                             order_type=OrderType.TAKEAWAY, order_status=OrderStatus.CONFIRMED,
                             payment_method=PaymentMethod.CASH, subtotal=amount, total_amount=amount))
            await db.commit()
            report = next(row for row in await ShiftsService(db).get_shifts_report(shift.target_date) if row["id"] == shift.id)
            assert report["total_orders"] == 1
            assert report["cash_sales"] == 100
            assert report["expected_cash"] == 400
            orders = await get_report_orders(db, shift.target_date, shift.target_date, 20, 0, shift)
            assert [o.order_number for o in orders] == ["PRE"]
            assert orders[0].created_at_time == "06:59 AM"
            activity = await get_activity_breakdown(db, shift.target_date, shift.target_date, shift)
            assert [(row.hour, row.count) for row in activity] == [(6, 1)]
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_legacy_shift_before_seven_retains_its_orders():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            cashier = User(username="legacy-winter", phone="01099999998", hashed_password="x", role=UserRole.CASHIER)
            db.add(cashier)
            await db.flush()
            shift = CashierShift(user_id=cashier.id, target_date=date(2026, 10, 31),
                                 start_time=naive(2026, 10, 31, 4), end_time=naive(2026, 10, 31, 5),
                                 opening_cash=Decimal(300), cash_tracking_enabled=True)
            db.add(shift)
            db.add(Order(order_number="OLD", order_date=shift.target_date,
                         created_at=naive(2026, 10, 31, 7, 10), created_by_user_id=cashier.id,
                         order_source=OrderSource.CASHIER, order_type=OrderType.TAKEAWAY,
                         order_status=OrderStatus.CONFIRMED, payment_method=PaymentMethod.CASH,
                         subtotal=100, total_amount=100))
            await db.commit()
            report = next(row for row in await ShiftsService(db).get_shifts_report(shift.target_date) if row["id"] == shift.id)
            assert report["total_orders"] == 1
            assert report["expected_cash"] == 400
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_counter_uses_same_explicit_business_date_as_order():
    from app.modules.orders.repository import OrderRepository

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            db.add(Order(order_number="T-0001", order_date=date(2026, 10, 30),
                         order_source=OrderSource.CASHIER, order_type=OrderType.TAKEAWAY,
                         order_status=OrderStatus.CONFIRMED, payment_method=PaymentMethod.CASH,
                         subtotal=100, total_amount=100))
            await db.commit()
            repository = OrderRepository(db)
            repository.get_business_date = lambda: date(2026, 10, 31)
            number = await repository.get_next_order_number(date(2026, 10, 30))
            assert number.endswith("-0002")
            assert (await repository.get_next_order_number(date(2026, 10, 31))).endswith("-0001")
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_two_cashiers_across_repeated_hour_keep_separate_cash_and_expenses():
    from app.modules.orders.models import OrderStatusHistory
    from app.modules.shifts.models import ShiftExpense

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            a = User(username="repeat-a", phone="01099999991", hashed_password="x", role=UserRole.CASHIER)
            b = User(username="repeat-b", phone="01099999992", hashed_password="x", role=UserRole.CASHIER)
            db.add_all([a, b])
            await db.flush()
            day = date(2026, 10, 29)
            first = CashierShift(user_id=a.id, target_date=day, start_time=naive(2026, 10, 29, 19),
                                 end_time=naive(2026, 10, 29, 23), opening_cash=Decimal(300), cash_tracking_enabled=True)
            second = CashierShift(user_id=b.id, target_date=day, start_time=naive(2026, 10, 29, 19),
                                  end_time=naive(2026, 10, 29, 23), opening_cash=Decimal(300), cash_tracking_enabled=True)
            db.add_all([first, second])
            await db.flush()
            first_order = Order(order_number="BEFORE", order_date=day, created_at=naive(2026, 10, 29, 23, 30),
                                created_by_user_id=a.id, order_source=OrderSource.CASHIER, order_type=OrderType.TAKEAWAY,
                                order_status=OrderStatus.CONFIRMED, payment_method=PaymentMethod.CASH,
                                subtotal=100, total_amount=100)
            online_order = Order(order_number="AFTER", order_date=day, created_at=naive(2026, 10, 29, 23),
                                 created_by_user_id=b.id, order_source=OrderSource.ONLINE, order_type=OrderType.TAKEAWAY,
                                 order_status=OrderStatus.CONFIRMED, payment_method=PaymentMethod.CASH,
                                 subtotal=200, total_amount=200)
            db.add_all([first_order, online_order])
            await db.flush()
            db.add(OrderStatusHistory(order_id=online_order.id, status=OrderStatus.CONFIRMED,
                                      changed_by_user_id=b.id, changed_at=naive(2026, 10, 30, 0, 30)))
            db.add(ShiftExpense(shift_id=first.id, user_id=a.id, target_date=day,
                                title="test", amount=Decimal(20), paid_from="shift_cash"))
            await db.commit()
            reports = {row["id"]: row for row in await ShiftsService(db).get_shifts_report(day)}
            assert (reports[first.id]["cash_sales"], reports[first.id]["expected_cash"]) == (100, 380)
            assert (reports[second.id]["cash_sales"], reports[second.id]["expected_cash"]) == (200, 500)
            rows = await get_activity_breakdown(db, day, day)
            assert [(r.hour, r.count) for r in rows] == [(23, 2)]
    finally:
        await engine.dispose()
