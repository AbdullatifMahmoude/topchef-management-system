"""Cash custody journeys use an isolated database and never touch live orders."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - register all ORM tables
from app.core.business_calendar import business_day_start, get_current_business_date
from app.core.database import Base
from app.core.enums import (
    OrderSource,
    OrderStatus,
    OrderType,
    PaymentMethod,
    ProductType,
    UserRole,
)
from app.core.exceptions import AuthorizationError, ValidationError
from app.modules.menu.models import Category, Product, Variant
from app.modules.orders.models import (
    Order,
    OrderModificationHistory,
    OrderStatusHistory,
)
from app.modules.orders.repository import OrderRepository
from app.modules.orders.router import list_orders
from app.modules.orders.schemas import (
    OrderCreate,
    OrderItemCreate,
    OrderUpdate,
    OrderUpdateFull,
)
from app.modules.orders.service import OrderService
from app.modules.report.service import get_report_data, get_report_orders
from app.modules.shifts.cash_custody import (
    assert_financial_change_clear,
    movement_summary,
    record_customer_collection,
    record_direct_rider_settlement,
    record_rider_handoff,
    reverse_movement,
)
from app.modules.shifts.models import (
    CashierShift,
    ShiftCloseSnapshot,
    ShiftExpense,
    ShiftExpenseAudit,
)
from app.modules.shifts.router import (
    AdminExpenseCreate,
    AdminExpenseUpdate,
    ShiftCashAdjustmentCreate,
    ShiftCloseConfirmation,
    confirm_shift_close,
    create_admin_expense,
    get_order_cash_status,
    record_post_close_adjustment,
    rider_cash_outstanding,
    rider_cash_pending_direct_settlement,
    update_admin_expense,
)
from app.modules.shifts.service import ShiftsService
from app.modules.users.models import User


@pytest.fixture
async def cash_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def seed(cash_db):
    target_date = get_current_business_date()
    local_start = business_day_start(target_date)
    cashier = User(username="custody-cashier", full_name="Cashier", role=UserRole.CASHIER,
                   phone="01000003001", hashed_password="test")
    other = User(username="custody-other", full_name="Other", role=UserRole.CASHIER,
                 phone="01000003002", hashed_password="test")
    rider = User(username="custody-rider", full_name="Rider", role=UserRole.DELIVERY,
                 phone="01000003003", hashed_password="test")
    admin = User(username="custody-admin", full_name="Admin", role=UserRole.ADMIN,
                 phone="01000003004", hashed_password="test")
    cash_db.add_all([cashier, other, rider, admin])
    await cash_db.flush()
    shift = CashierShift(user_id=cashier.id, target_date=target_date,
                         start_time=local_start - timedelta(hours=3),
                         opening_cash=Decimal("300.00"), cash_tracking_enabled=True,
                         opening_confirmed_at=datetime.now(UTC))
    other_shift = CashierShift(user_id=other.id, target_date=target_date,
                               start_time=local_start - timedelta(hours=3),
                               opening_cash=Decimal("300.00"), cash_tracking_enabled=True,
                               opening_confirmed_at=datetime.now(UTC))
    cash_db.add_all([shift, other_shift])
    await cash_db.flush()
    return cashier, other, rider, admin, shift, local_start + timedelta(hours=1)


async def order(cash_db, number, cashier, created_at, amount, kind=OrderType.TAKEAWAY, rider=None, fee="0.00"):
    row = Order(order_number=number, order_date=get_current_business_date(),
                order_source=OrderSource.CASHIER, order_status=OrderStatus.CONFIRMED,
                order_type=kind, payment_method=PaymentMethod.CASH,
                created_by_user_id=cashier.id, delivery_person_id=rider.id if rider else None,
                created_at=created_at, subtotal=Decimal(amount) - Decimal(fee),
                total_amount=Decimal(amount), delivery_fee=Decimal(fee),
                discount_amount=Decimal("0.00"), cash_tracking_enabled=True)
    cash_db.add(row)
    await cash_db.flush()
    return row


@pytest.mark.asyncio
async def test_collection_attestation_does_not_change_expected_cash_and_close_is_frozen(cash_db, monkeypatch):
    cashier, _, _, admin, shift, created_at = await seed(cash_db)
    paid = await order(cash_db, "CASH-1", cashier, created_at, "50.00")
    await order(cash_db, "CASH-2", cashier, created_at, "80.00")
    first = await record_customer_collection(cash_db, paid.id, cashier, "checkout-cash-1")
    same = await record_customer_collection(cash_db, paid.id, cashier, "checkout-cash-1")
    assert first.id == same.id
    cash_db.add(ShiftExpense(shift_id=shift.id, user_id=cashier.id, target_date=shift.target_date,
                             title="Supplies", amount=Decimal("20.00"), paid_from="shift_cash"))
    cash_db.add(ShiftExpense(shift_id=shift.id, user_id=admin.id, target_date=shift.target_date,
                             title="Admin purchase", amount=Decimal("15.00"), paid_from="admin_cash"))
    await cash_db.commit()

    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                  if row["id"] == shift.id)
    assert report["cash_sales"] == 130
    assert report["confirmed_cash"] == 50
    assert report["unconfirmed_cash_sales"] == 80
    assert report["cash_expenses"] == 20
    assert report["expected_cash"] == 410

    shift.actual_closing_cash = Decimal("410.00")
    await cash_db.commit()
    await ShiftsService(cash_db).end_shift(cashier.id)
    snapshot = await cash_db.scalar(select(ShiftCloseSnapshot).where(ShiftCloseSnapshot.shift_id == shift.id))
    assert snapshot.expected_cash == Decimal("410.00")
    assert snapshot.difference == Decimal("0.00")
    confirmation = await confirm_shift_close(
        shift.id, ShiftCloseConfirmation(admin_count=Decimal("410.00")), cash_db, admin
    )
    assert confirmation["count_difference"] == 0
    with pytest.raises(ValidationError):
        await confirm_shift_close(shift.id, ShiftCloseConfirmation(admin_count=Decimal("410.00")), cash_db, admin)

    cash_db.add(ShiftExpense(shift_id=shift.id, user_id=admin.id, target_date=shift.target_date,
                             title="Recorded later", amount=Decimal("9.00"), paid_from="shift_cash",
                             created_at=datetime.now(UTC) + timedelta(seconds=2)))
    await cash_db.commit()
    after = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                 if row["id"] == shift.id)
    assert after["expected_cash"] == 410
    assert after["cash_difference"] == 0
    assert after["late_cash_expenses"] == 9


@pytest.mark.asyncio
async def test_closed_shift_keeps_its_prechange_expected_cash_snapshot(cash_db):
    cashier, _, _, _, shift, created_at = await seed(cash_db)
    await order(cash_db, "OLD-SNAPSHOT", cashier, created_at, "80.00")
    shift.end_time = datetime.now(UTC).replace(tzinfo=None)
    shift.actual_closing_cash = Decimal("300.00")
    cash_db.add(ShiftCloseSnapshot(
        shift_id=shift.id, opening_cash=Decimal("300.00"),
        confirmed_cash=Decimal("0.00"), unconfirmed_cash_sales=Decimal("80.00"),
        cash_expenses=Decimal("0.00"), expected_cash=Decimal("300.00"),
        cashier_count=Decimal("300.00"), difference=Decimal("0.00"),
    ))
    await cash_db.commit()
    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                  if row["id"] == shift.id)
    assert report["cash_sales"] == 80.0
    assert report["expected_cash"] == 300.0
    assert report["cash_difference"] == 0.0


@pytest.mark.asyncio
async def test_rider_collection_cross_shift_handoff_stays_minimal(cash_db):
    cashier, other, rider, admin, _, created_at = await seed(cash_db)
    delivery = await order(cash_db, "DEL-1", cashier, created_at, "110.00",
                           OrderType.DELIVERY, rider, "10.00")
    before = await movement_summary(cash_db, delivery)
    assert before["uncollected"] == Decimal("100.00")
    with pytest.raises(ValidationError):
        await record_rider_handoff(cash_db, delivery.id, cashier, Decimal("100.00"), "handoff-before-cash")
    await record_customer_collection(cash_db, delivery.id, rider, "rider-collected-1")
    with pytest.raises(AuthorizationError):
        await get_order_cash_status(delivery.id, cash_db, other)
    other_handoff = await record_rider_handoff(cash_db, delivery.id, other, Decimal("20.00"), "other-cashier-1")
    handoff = await record_rider_handoff(cash_db, delivery.id, cashier, Decimal("40.00"), "handoff-partial-1")
    assert (await record_rider_handoff(cash_db, delivery.id, cashier, Decimal("40.00"), "handoff-partial-1")).id == handoff.id
    summary = await movement_summary(cash_db, delivery)
    assert summary["customer_paid"] == Decimal("100.00")
    assert summary["rider_holding"] == Decimal("40.00")
    assert summary["cashier_received"] == Decimal("60.00")
    with pytest.raises(ValidationError):
        await assert_financial_change_clear(cash_db, delivery)
    with pytest.raises(ValidationError):
        await reverse_movement(cash_db, summary["movements"][0].id, admin, "reverse-rider-first", "Refund")
    await reverse_movement(cash_db, handoff.id, admin, "reverse-handoff-1", "Cash returned to rider")
    await cash_db.commit()
    assert (await movement_summary(cash_db, delivery))["rider_holding"] == Decimal("80.00")
    assert other_handoff.shift_id != handoff.shift_id


@pytest.mark.asyncio
async def test_direct_rider_settlement_requires_full_physical_handoff_and_is_idempotent(cash_db):
    cashier, _, rider, admin, shift, created_at = await seed(cash_db)
    delivery = await order(cash_db, "DIRECT-RIDER-1", cashier, created_at, "110.00",
                           OrderType.DELIVERY, rider, "10.00")
    pending = await rider_cash_pending_direct_settlement(cash_db, cashier)
    assert [(row["order_id"], row["rider_id"], row["restaurant_cash_due_from_rider"])
            for row in pending] == [(delivery.id, rider.id, 100.0)]
    with pytest.raises(AuthorizationError):
        await record_direct_rider_settlement(cash_db, delivery.id, admin, Decimal("100.00"), "direct-admin-1")
    with pytest.raises(ValidationError, match="كاملة"):
        await record_direct_rider_settlement(cash_db, delivery.id, cashier, Decimal("90.00"), "direct-short-1")
    assert (await movement_summary(cash_db, delivery))["cashier_received"] == 0
    handed = await record_direct_rider_settlement(
        cash_db, delivery.id, cashier, Decimal("100.00"), "direct-cashier-1",
    )
    assert handed.shift_id == shift.id
    assert handed.actor_id == cashier.id
    assert handed.rider_id == rider.id
    assert (await record_direct_rider_settlement(
        cash_db, delivery.id, cashier, Decimal("100.00"), "direct-cashier-1",
    )).id == handed.id
    summary = await movement_summary(cash_db, delivery)
    assert len(summary["movements"]) == 2
    assert all(row.actor_id == cashier.id and "إقرار كاشير" in row.note for row in summary["movements"])
    assert summary["customer_paid"] == Decimal("100.00")
    assert summary["cashier_received"] == Decimal("100.00")
    assert summary["rider_holding"] == Decimal("0.00")
    assert await rider_cash_pending_direct_settlement(cash_db, cashier) == []
    assert await rider_cash_outstanding(cash_db, cashier) == []
    with pytest.raises(ValidationError, match="تحصيل مسجل"):
        await record_direct_rider_settlement(cash_db, delivery.id, cashier, Decimal("100.00"), "direct-second-1")


@pytest.mark.asyncio
async def test_cashier_can_attest_delivered_predeploy_order_without_assigned_rider(cash_db):
    cashier, _, _, admin, shift, created_at = await seed(cash_db)
    shift.cash_tracking_enabled = False
    old_delivery = await order(cash_db, "OLD-UNASSIGNED", cashier, created_at,
                               "210.00", OrderType.DELIVERY, fee="10.00")
    old_delivery.cash_tracking_enabled = False
    old_delivery.order_status = OrderStatus.DELIVERED
    await order(cash_db, "NEW-TRACKED", cashier, created_at + timedelta(minutes=1), "25.00")
    await cash_db.flush()

    pending = await rider_cash_pending_direct_settlement(cash_db, cashier)
    assert [(row["order_id"], row["rider_id"], row["restaurant_cash_due_from_rider"])
            for row in pending] == [(old_delivery.id, None, 200.0)]
    before = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                  if row["id"] == shift.id)
    assert before["expected_cash"] == 525.0
    assert before["delivery_cash_sales"] == 200.0
    assert before["cash_sales"] == 225.0  # 210 paid minus the rider's 10 delivery fee, plus 25 takeaway.
    assert before["unconfirmed_delivery_cash"] == 200.0
    with pytest.raises(AuthorizationError):
        await record_direct_rider_settlement(cash_db, old_delivery.id, admin, Decimal("200.00"), "old-admin")
    with pytest.raises(ValidationError, match="كاملة"):
        await record_direct_rider_settlement(cash_db, old_delivery.id, cashier, Decimal("190.00"), "old-short")
    handoff = await record_direct_rider_settlement(cash_db, old_delivery.id, cashier,
                                                    Decimal("200.00"), "old-cashier")
    assert handoff.rider_id is None and handoff.actor_id == cashier.id
    assert "غير مسند" in handoff.note
    assert (await record_direct_rider_settlement(cash_db, old_delivery.id, cashier,
                                                  Decimal("200.00"), "old-cashier")).id == handoff.id
    summary = await movement_summary(cash_db, old_delivery)
    assert summary["customer_paid"] == Decimal("200.00")
    assert summary["cashier_received"] == Decimal("200.00")
    assert summary["rider_holding"] == Decimal("0.00")
    assert await rider_cash_pending_direct_settlement(cash_db, cashier) == []
    after = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                 if row["id"] == shift.id)
    assert after["expected_cash"] == before["expected_cash"]
    assert after["confirmed_cash"] == before["confirmed_cash"] + 200.0
    assert after["unconfirmed_delivery_cash"] == 0.0

    new_unassigned = await order(cash_db, "NEW-UNASSIGNED", cashier, created_at,
                                 "110.00", OrderType.DELIVERY, fee="10.00")
    new_unassigned.order_status = OrderStatus.DELIVERED
    await cash_db.flush()
    with pytest.raises(ValidationError, match="مسندًا"):
        await record_direct_rider_settlement(cash_db, new_unassigned.id, cashier,
                                             Decimal("100.00"), "new-unassigned")


@pytest.mark.asyncio
async def test_shift_order_filters_reach_older_hall_orders_and_payment_methods(cash_db):
    cashier, other, _, _, shift, created_at = await seed(cash_db)
    for index in range(35):
        await order(cash_db, f"HALL-{index}", cashier, created_at + timedelta(minutes=index),
                    "20.00", OrderType.HALL)
    wallet = await order(cash_db, "HALL-WALLET", cashier, created_at + timedelta(hours=1),
                         "30.00", OrderType.HALL)
    wallet.payment_method = PaymentMethod.WALLET
    await order(cash_db, "OTHER-HALL", other, created_at, "40.00", OrderType.HALL)
    await cash_db.flush()
    repository = OrderRepository(cash_db)
    total, rows = await repository.list_orders_paginated(
        source=OrderSource.CASHIER, shift=shift, cashier_id=cashier.id,
        order_type=OrderType.HALL, page=2, page_size=30,
    )
    assert total == 36
    assert len(rows) == 6
    assert "HALL-0" in {row.order_number for row in rows}
    total, rows = await repository.list_orders_paginated(
        source=OrderSource.CASHIER, shift=shift, cashier_id=cashier.id,
        payment_method=PaymentMethod.WALLET, search="HALL-WALLET",
    )
    assert total == 1 and [row.id for row in rows] == [wallet.id]
    with pytest.raises(AuthorizationError):
        await list_orders(source=OrderSource.CASHIER, shift_id=shift.id,
                          service=OrderService(cash_db), current_user=other)


@pytest.mark.asyncio
async def test_shift_order_window_uses_project_cairo_offset(cash_db):
    cashier, _, _, _, shift, _ = await seed(cash_db)
    shift.start_time = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    shift.end_time = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    inside = await order(cash_db, "WINDOW-IN", cashier,
                         datetime(2026, 11, 1, 13, 30, tzinfo=UTC).replace(tzinfo=None), "20.00")
    await order(cash_db, "WINDOW-OUT", cashier,
                datetime(2026, 11, 1, 12, 30, tzinfo=UTC).replace(tzinfo=None), "20.00")
    total, rows = await OrderRepository(cash_db).list_orders_paginated(
        source=OrderSource.CASHIER, shift=shift, cashier_id=cashier.id,
    )
    assert total == 1 and [row.id for row in rows] == [inside.id]


@pytest.mark.asyncio
async def test_predeploy_cash_orders_in_same_mixed_shift_are_pending_until_received(cash_db):
    cashier, _, rider, _, shift, created_at = await seed(cash_db)
    shift.cash_tracking_enabled = False
    shift.opening_cash = Decimal("0.00")
    shift.opening_confirmed_at = None
    legacy = await order(cash_db, "CUTOVER-OLD", cashier, created_at, "100.00")
    legacy.cash_tracking_enabled = False
    await cash_db.flush()
    assert (await get_order_cash_status(legacy.id, cash_db, cashier))["cash_collection_available"] is False


    tracked = await order(cash_db, "CUTOVER-NEW", cashier, created_at + timedelta(minutes=1), "50.00")
    await cash_db.flush()
    await record_customer_collection(cash_db, tracked.id, cashier, "new-cutover-1")

    status = await get_order_cash_status(legacy.id, cash_db, cashier)
    assert status["cash_tracking_enabled"] is False
    assert status["cash_collection_available"] is True
    assert status["legacy_same_shift"] is True
    assert status["uncollected"] == 100.0
    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                  if row["id"] == shift.id)
    assert report["cash_tracking_enabled"] is True
    assert report["confirmed_cash"] == 50.0
    assert report["unconfirmed_cash_sales"] == 100.0
    assert report["expected_cash"] == 150.0

    first = await record_customer_collection(cash_db, legacy.id, cashier, "old-cutover-1")
    assert (await record_customer_collection(cash_db, legacy.id, cashier, "old-cutover-1")).id == first.id
    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                  if row["id"] == shift.id)
    assert report["confirmed_cash"] == 150.0
    assert report["unconfirmed_cash_sales"] == 0.0
    assert report["expected_cash"] == 150.0

    old_shift_order = await order(cash_db, "PRIOR-SHIFT", cashier, created_at - timedelta(hours=2), "25.00")
    old_shift_order.cash_tracking_enabled = False
    await cash_db.flush()
    assert (await get_order_cash_status(old_shift_order.id, cash_db, cashier))["cash_collection_available"] is False
    with pytest.raises(ValidationError, match="شيفت قديم"):
        await record_customer_collection(cash_db, old_shift_order.id, cashier, "prior-shift-1")

    legacy_delivery = await order(cash_db, "CUTOVER-DELIVERY", cashier, created_at,
                                  "110.00", OrderType.DELIVERY, rider, "10.00")
    legacy_delivery.cash_tracking_enabled = False
    await cash_db.flush()
    pending = await rider_cash_pending_direct_settlement(cash_db, cashier)
    assert legacy_delivery.id in {row["order_id"] for row in pending}
    await record_direct_rider_settlement(cash_db, legacy_delivery.id, cashier, Decimal("100.00"), "old-delivery-1")
    assert (await movement_summary(cash_db, legacy_delivery))["cashier_received"] == Decimal("100.00")

    shift.opening_confirmed_at = datetime.now(UTC)
    shift.actual_closing_cash = Decimal("250.00")
    await cash_db.commit()
    await ShiftsService(cash_db).end_shift(cashier.id)
    assert shift.cash_tracking_enabled is True
    snapshot = await cash_db.scalar(select(ShiftCloseSnapshot).where(ShiftCloseSnapshot.shift_id == shift.id))
    assert snapshot.expected_cash == Decimal("250.00")
    assert snapshot.difference == Decimal("0.00")
    assert (await get_order_cash_status(legacy.id, cash_db, cashier))["cash_collection_available"] is False


@pytest.mark.asyncio
async def test_closed_shift_from_previous_day_keeps_legacy_financial_calculation(cash_db):
    cashier, _, _, _, shift, _ = await seed(cash_db)
    past_date = shift.target_date - timedelta(days=1)
    start_local = business_day_start(past_date)
    shift.target_date = past_date
    shift.start_time = (start_local - timedelta(hours=3)).replace(tzinfo=UTC)
    shift.end_time = None
    shift.cash_tracking_enabled = False
    tracked_order = await order(cash_db, "PAST-TRACKED", cashier,
                                start_local + timedelta(hours=1), "50.00")
    tracked_order.order_date = past_date
    await cash_db.flush()

    assert await ShiftsService(cash_db).shift_uses_cash_ledger(shift) is False
    open_report = next(row for row in await ShiftsService(cash_db).get_shifts_report(past_date)
                       if row["id"] == shift.id)
    assert open_report["cash_tracking_enabled"] is False
    shift.end_time = shift.start_time + timedelta(hours=4)
    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(past_date)
                  if row["id"] == shift.id)
    assert report["cash_tracking_enabled"] is False
    assert report["expected_cash"] == 350.0


@pytest.mark.asyncio
async def test_only_approved_cutover_shift_keeps_ledger_after_day_boundary(cash_db, monkeypatch):
    cashier, _, _, _, _, _ = await seed(cash_db)
    past_date = get_current_business_date()
    start_local = business_day_start(past_date)
    cutover = CashierShift(
        id=135, user_id=cashier.id, target_date=past_date,
        start_time=(start_local - timedelta(hours=3)).replace(tzinfo=UTC),
        opening_cash=Decimal("0.00"), cash_tracking_enabled=False,
    )
    cash_db.add(cutover)
    tracked = await order(cash_db, "CUTOVER-OVERNIGHT", cashier,
                          start_local + timedelta(hours=1), "50.00")
    tracked.order_date = past_date
    legacy_delivery = await order(cash_db, "CUTOVER-OVERNIGHT-OLD", cashier,
                                  start_local + timedelta(hours=1), "110.00",
                                  OrderType.DELIVERY, fee="10.00")
    legacy_delivery.cash_tracking_enabled = False
    legacy_delivery.order_status = OrderStatus.DELIVERED
    legacy_delivery.order_date = past_date
    await cash_db.flush()
    monkeypatch.setattr("app.modules.shifts.service.get_current_business_date", lambda: past_date + timedelta(days=1))
    monkeypatch.setattr("app.modules.shifts.cash_custody.get_current_business_date", lambda: past_date + timedelta(days=1))
    monkeypatch.setattr(import_module("app.modules.shifts.router"), "get_business_date",
                        lambda: past_date + timedelta(days=1))
    assert await ShiftsService(cash_db).shift_uses_cash_ledger(cutover) is True
    assert (await get_order_cash_status(legacy_delivery.id, cash_db, cashier))["cash_collection_available"] is True
    assert legacy_delivery.id in {row["order_id"] for row in await rider_cash_pending_direct_settlement(cash_db, cashier)}
    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(past_date)
                  if row["id"] == cutover.id)
    assert report["cash_tracking_enabled"] is True
    assert report["unconfirmed_cash_sales"] == 150.0
    assert report["expected_cash"] == 150.0


@pytest.mark.asyncio
async def test_report_orders_page_from_oldest_and_expose_detail_id(cash_db):
    cashier, _, _, _, _, created_at = await seed(cash_db)
    oldest = await order(cash_db, "REPORT-OLD", cashier, created_at, "20.00")
    middle = await order(cash_db, "REPORT-MID", cashier, created_at + timedelta(minutes=1), "30.00")
    newest = await order(cash_db, "REPORT-NEW", cashier, created_at + timedelta(minutes=2), "40.00")
    target_date = get_current_business_date()
    first_page = await get_report_orders(cash_db, target_date, target_date, limit=2, offset=0)
    second_page = await get_report_orders(cash_db, target_date, target_date, limit=2, offset=2)
    assert [(row.id, row.order_number) for row in first_page] == [
        (oldest.id, oldest.order_number), (middle.id, middle.order_number),
    ]
    assert [(row.id, row.order_number) for row in second_page] == [(newest.id, newest.order_number)]


@pytest.mark.asyncio
async def test_expense_source_and_post_close_edit_are_audited(cash_db, monkeypatch):
    _, _, _, admin, shift, _ = await seed(cash_db)
    async def emit(_event):
        return None
    monkeypatch.setattr("app.core.events.order_events_manager.emit", emit)
    created = await create_admin_expense(
        AdminExpenseCreate(title="Fuel", amount=Decimal("25.00"), target_date=shift.target_date,
                           shift_id=shift.id, paid_from="admin_cash", receipt_reference="INV-5"),
        cash_db, admin,
    )
    audits = (await cash_db.execute(select(ShiftExpenseAudit).where(
        ShiftExpenseAudit.expense_id == created["id"]
    ))).scalars().all()
    assert created["paid_from"] == "admin_cash"
    assert audits[0].after_values["receipt_reference"] == "INV-5"
    shift.end_time = datetime.now(UTC)
    await cash_db.commit()
    with pytest.raises(ValidationError):
        await update_admin_expense(
            created["id"], AdminExpenseUpdate(amount=Decimal("30.00")), cash_db, admin,
        )


@pytest.mark.asyncio
async def test_limited_rider_list_and_post_close_adjustment(cash_db):
    cashier, other, rider, admin, shift, created_at = await seed(cash_db)
    takeaway = await order(cash_db, "TAKE-1", cashier, created_at, "15.00")
    with pytest.raises(AuthorizationError):
        await record_customer_collection(cash_db, takeaway.id, other, "other-takeaway-1")
    await record_customer_collection(cash_db, takeaway.id, cashier, "own-takeaway-1")
    with pytest.raises(ValidationError):
        await record_customer_collection(cash_db, takeaway.id, cashier, "another-collection-1")
    delivery = await order(cash_db, "DEL-2", cashier, created_at, "77.50",
                           OrderType.DELIVERY, rider, "7.50")
    await record_customer_collection(cash_db, delivery.id, rider, "rider-collected-2")
    limited = await rider_cash_outstanding(cash_db, other)
    assert limited == [{"rider_id": rider.id, "order_id": delivery.id,
                        "rider_name": rider.full_name, "order_number": "DEL-2",
                        "restaurant_cash_due_from_rider": 70.0}]
    await record_rider_handoff(cash_db, delivery.id, other, Decimal("20.00"), "other-handoff-2")
    assert (await rider_cash_outstanding(cash_db, other))[0]["restaurant_cash_due_from_rider"] == 50.0
    shift.actual_closing_cash = Decimal("315.00")
    await cash_db.commit()
    await ShiftsService(cash_db).end_shift(cashier.id)
    with pytest.raises(AuthorizationError):
        await record_post_close_adjustment(
            shift.id, ShiftCashAdjustmentCreate(amount=Decimal("5.00"), reason="Recovered",
                                                 idempotency_key="adjust-cashier-1"), cash_db, cashier,
        )
    payload = ShiftCashAdjustmentCreate(amount=Decimal("5.00"), reason="Recovered",
                                         idempotency_key="adjust-admin-1")
    first = await record_post_close_adjustment(shift.id, payload, cash_db, admin)
    second = await record_post_close_adjustment(shift.id, payload, cash_db, admin)
    assert first["id"] == second["id"]
    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                  if row["id"] == shift.id)
    assert report["expected_cash"] == 385
    assert report["cash_difference"] == -70
    assert report["adjusted_closing_cash"] == 320
    assert report["difference_after_adjustments"] == -65
    assert report["post_close_adjustments_total"] == 5
    await record_post_close_adjustment(
        shift.id,
        ShiftCashAdjustmentCreate(amount=Decimal("65.00"), reason="Delivery cash handed over",
                                  idempotency_key="adjust-delivery-1"),
        cash_db, admin,
    )
    settled = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                   if row["id"] == shift.id)
    assert settled["cash_difference"] == -70  # The cashier's count at close stays frozen.
    assert settled["difference_after_adjustments"] == 0
    assert settled["post_close_adjustments_total"] == 70


@pytest.mark.asyncio
async def test_online_order_counts_in_shift_that_confirmed_it(cash_db):
    cashier, _, _, _, shift, created_at = await seed(cash_db)
    shift.start_time = created_at + timedelta(minutes=5) - timedelta(hours=3)
    online = await order(cash_db, "WEB-BEFORE-SHIFT", cashier, created_at, "80.00")
    online.order_source = OrderSource.ONLINE
    cash_db.add(OrderStatusHistory(
        order_id=online.id, status=OrderStatus.CONFIRMED,
        changed_by_user_id=cashier.id, changed_at=created_at + timedelta(minutes=10),
    ))
    await record_customer_collection(cash_db, online.id, cashier, "web-before-shift-cash")
    await cash_db.commit()
    report = next(row for row in await ShiftsService(cash_db).get_shifts_report(shift.target_date)
                  if row["id"] == shift.id)
    assert report["total_orders"] == 1
    assert report["cash_sales"] == 80
    assert report["confirmed_cash"] == 80
    assert report["expected_cash"] == 380


@pytest.mark.asyncio
async def test_general_report_attributes_prior_day_online_order_to_accepting_shift(cash_db):
    cashier, _, _, _, shift, created_at = await seed(cash_db)
    shift.start_time = created_at + timedelta(minutes=5) - timedelta(hours=3)
    online = await order(cash_db, "WEB-REPORT-PRIOR-DAY", cashier, created_at, "80.00")
    online.order_source = OrderSource.ONLINE
    online.order_date = shift.target_date - timedelta(days=1)
    cash_db.add(OrderStatusHistory(
        order_id=online.id, status=OrderStatus.CONFIRMED,
        changed_by_user_id=cashier.id, changed_at=created_at + timedelta(minutes=10),
    ))
    await cash_db.commit()

    data = await get_report_data(cash_db, shift.target_date, shift.target_date, 50, 0, shift.id)
    assert data["summary"].total_orders == 1
    assert data["summary"].total_revenue == Decimal("80.00")
    assert [row.order_number for row in data["orders"]] == [online.order_number]
    assert data["revenue_trend"][0].period_date == shift.target_date


@pytest.mark.asyncio
async def test_payment_method_correction_records_actor_and_values(cash_db, monkeypatch):
    cashier, _, _, _, _, created_at = await seed(cash_db)
    paid = await order(cash_db, "PAYMENT-AUDIT-1", cashier, created_at, "50.00")
    await cash_db.commit()
    monkeypatch.setattr("app.modules.orders.service.order_events_manager.emit", AsyncMock())
    service = OrderService(
        cash_db, pricing_service=AsyncMock(), offer_service=AsyncMock(),
        notification_service=AsyncMock(),
    )
    await service.update_order(
        paid.id, OrderUpdateFull(payment_method=PaymentMethod.WALLET, digital_payment_verified=True), cashier.id,
    )
    await cash_db.commit()
    changes = (await cash_db.execute(select(OrderModificationHistory).where(
        OrderModificationHistory.order_id == paid.id
    ))).scalars().all()
    assert len(changes) == 1
    assert changes[0].changed_by_user_id == cashier.id
    assert "cash" in changes[0].changes[0]
    assert "wallet" in changes[0].changes[0]
    assert paid.digital_payment_verified_by_user_id == cashier.id
    assert paid.digital_payment_verified_at is not None


@pytest.mark.asyncio
async def test_cashier_order_requires_open_confirmed_current_shift(cash_db):
    cashier, _, _, _, shift, _ = await seed(cash_db)
    cashier_id = cashier.id
    service = OrderService(cash_db, notification_service=AsyncMock())
    payload = OrderCreate(
        source=OrderSource.CASHIER, order_type=OrderType.TAKEAWAY,
        payment_method=PaymentMethod.CASH,
        items=[OrderItemCreate(product_id=999, quantity=1, unit_price=Decimal("10.00"))],
    )
    shift.opening_confirmed_at = None
    await cash_db.commit()
    with pytest.raises(ValidationError, match="عهدة بداية الشيفت"):
        await service.create_order(payload, cashier_id)
    assert await cash_db.scalar(select(Order.id).where(Order.created_by_user_id == cashier_id)) is None


@pytest.mark.asyncio
async def test_cashier_wallet_order_records_verified_actor_and_no_drawer_cash(cash_db, monkeypatch):
    cashier, _, _, _, _, _ = await seed(cash_db)
    product = Product(
        category=Category(cat_name="Digital checkout"), product_name="Meal",
        product_type=ProductType.SIMPLE, is_available=True,
        variants=[Variant(name="Regular", price=Decimal("85.00"))],
    )
    cash_db.add(product)
    await cash_db.commit()
    cashier_id = cashier.id
    pricing = AsyncMock()
    pricing.calculate_price.return_value = SimpleNamespace(
        subtotal=Decimal("85.00"), discount_amount=Decimal("0.00"),
        delivery_fee=Decimal("0.00"), total_amount=Decimal("85.00"),
    )
    monkeypatch.setattr("app.modules.orders.service.order_events_manager.emit", AsyncMock())
    service = OrderService(cash_db, pricing_service=pricing, notification_service=AsyncMock())
    base = {
        "source": OrderSource.CASHIER, "order_type": OrderType.TAKEAWAY,
        "payment_method": PaymentMethod.WALLET,
        "items": [OrderItemCreate(product_id=product.id, quantity=1, unit_price=Decimal("85.00"))],
    }
    with pytest.raises(ValidationError, match="وصول تحويل"):
        await service.create_order(OrderCreate(**base), cashier_id)
    await cash_db.rollback()
    saved = await service.create_order(OrderCreate(**base, digital_payment_verified=True), cashier_id)
    assert saved.payment_method == PaymentMethod.WALLET
    assert saved.digital_payment_verified_by_user_id == cashier_id
    assert saved.digital_payment_verified_at is not None
    assert (await movement_summary(cash_db, saved))["cashier_received"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_online_instapay_needs_cashier_verified_receipt_before_acceptance(cash_db, monkeypatch):
    cashier, _, _, _, _, created_at = await seed(cash_db)
    web = await order(cash_db, "WEB-INSTAPAY-CHECK", cashier, created_at, "85.00")
    web.order_source = OrderSource.ONLINE
    web.order_status = OrderStatus.NEW
    web.payment_method = PaymentMethod.INSTAPAY
    web.created_by_user_id = None
    await cash_db.commit()
    web_id = web.id
    cashier_id = cashier.id
    monkeypatch.setattr("app.modules.orders.service.order_events_manager.emit", AsyncMock())
    service = OrderService(cash_db, notification_service=AsyncMock())
    with pytest.raises(ValidationError, match="التحويل وصل"):
        await service.update_order_status(web_id, OrderUpdate(order_status=OrderStatus.CONFIRMED), cashier_id)
    await cash_db.rollback()
    stored = await cash_db.get(Order, web_id)
    assert stored.order_status == OrderStatus.NEW
    assert stored.digital_payment_verified_at is None
    await service.update_order_status(
        web_id, OrderUpdate(order_status=OrderStatus.CONFIRMED, digital_payment_verified=True), cashier_id,
    )
    await cash_db.commit()
    await cash_db.refresh(stored)
    assert stored.order_status == OrderStatus.CONFIRMED
    assert stored.digital_payment_verified_by_user_id == cashier_id
    assert stored.digital_payment_verified_at is not None


@pytest.mark.asyncio
async def test_next_shift_waits_for_all_cashier_counts_and_admin_signoffs(cash_db):
    cashier, other, _, admin, _, _ = await seed(cash_db)
    next_cashier = User(
        username="next-cashier", full_name="Next", role=UserRole.CASHIER,
        phone="01000003005", hashed_password="test",
    )
    cash_db.add(next_cashier)
    await cash_db.flush()
    service = ShiftsService(cash_db)
    with pytest.raises(ValidationError, match="ما زال مفتوحًا"):
        await service.start_shift(next_cashier.id)

    shifts = (await cash_db.execute(select(CashierShift).where(
        CashierShift.user_id.in_([cashier.id, other.id])
    ))).scalars().all()
    for owner in (cashier, other):
        owned = next(row for row in shifts if row.user_id == owner.id)
        owned.actual_closing_cash = Decimal("300.00")
        await cash_db.commit()
        await service.end_shift(owner.id)

    with pytest.raises(ValidationError, match="لم تعتمد"):
        await service.start_shift(next_cashier.id)
    for closed in shifts:
        await confirm_shift_close(
            closed.id, ShiftCloseConfirmation(admin_count=Decimal("300.00")),
            cash_db, admin,
        )
    opened = await service.start_shift(next_cashier.id)
    assert opened.id not in {row.id for row in shifts}
    assert opened.opening_cash == Decimal("300.00")
    assert opened.cash_tracking_enabled
