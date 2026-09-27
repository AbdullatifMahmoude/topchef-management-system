import importlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - register ORM models
from app.core.database import Base
from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError, ValidationError
from app.modules.customer.models import (
    CustomerAddress,  # noqa: F401 - register ORM relationship
)
from app.modules.menu.models import Product  # noqa: F401 - register ORM relationship
from app.modules.offer.models import (
    OfferUsage,  # noqa: F401 - register ORM relationship
)
from app.modules.shifts.models import CashierShift, ShiftExpense
from app.modules.shifts.service import ShiftsService
from app.modules.users.models import User

router = importlib.import_module("app.modules.shifts.router")


class RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class ListDB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _query):
        return RowsResult(self.rows)


class WriteDB:
    def __init__(self):
        self.added = None
        self.shift = SimpleNamespace(id=4, user_id=2, target_date=date(2026, 9, 21))
        self.owner = user(UserRole.CASHIER, 2)

    def add(self, value):
        self.added = value

    async def get(self, model, _id):
        return self.shift if model.__name__ == "CashierShift" else self.owner

    async def commit(self):
        return None

    async def refresh(self, value):
        value.id = 11
        value.created_at = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def user(role=UserRole.ADMIN, user_id=1):
    return SimpleNamespace(id=user_id, role=role, full_name="مدير النظام", username="admin")


def expense(*, shift_id=None, amount="25.50"):
    return SimpleNamespace(
        id=7,
        shift_id=shift_id,
        user_id=1,
        target_date=date(2026, 9, 21),
        title="صيانة",
        amount=Decimal(amount),
        note="إصلاح بسيط",
        created_at=datetime(2026, 9, 21, 10, 0, tzinfo=UTC),
        is_deleted=False,
    )


@pytest.mark.asyncio
async def test_admin_lists_expenses_with_total_and_source():
    recorder = user()
    cashier = user(UserRole.CASHIER, 2)
    result = await router.list_admin_expenses(
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 21),
        db=ListDB([(expense(), recorder, None), (expense(shift_id=4, amount="10"), recorder, cashier)]),
        current_user=recorder,
    )

    assert result["count"] == 2
    assert result["total"] == 35.5
    assert result["items"][0]["source"] == "admin"
    assert result["items"][0]["editable_date"] is True
    assert result["items"][1]["source"] == "admin"
    assert result["items"][1]["shift_owner"] == cashier.full_name
    assert result["items"][1]["shift_id"] == 4
    assert result["items"][1]["editable_date"] is False


@pytest.mark.asyncio
async def test_cashier_cannot_use_admin_expense_api():
    with pytest.raises(AuthorizationError):
        await router.list_admin_expenses(
            start_date=date(2026, 9, 21),
            end_date=date(2026, 9, 21),
            db=ListDB([]),
            current_user=user(UserRole.CASHIER),
        )

    with pytest.raises(AuthorizationError):
        await router.list_admin_expense_shifts(
            target_date=date(2026, 9, 21), db=ListDB([]), current_user=user(UserRole.CASHIER),
        )


@pytest.mark.asyncio
async def test_admin_expense_range_must_be_ordered():
    with pytest.raises(ValidationError):
        await router.list_admin_expenses(
            start_date=date(2026, 9, 22),
            end_date=date(2026, 9, 21),
            db=ListDB([]),
            current_user=user(),
        )


@pytest.mark.asyncio
async def test_admin_created_expense_is_charged_to_selected_cashier_shift(monkeypatch):
    async def totals(_db, _shift_id, _target_date):
        assert _shift_id == 4
        return Decimal("75.00"), Decimal("75.00")

    async def emit(_payload):
        return None

    monkeypatch.setattr(router, "_expense_totals", totals)
    monkeypatch.setattr("app.core.events.order_events_manager.emit", emit)
    db = WriteDB()

    result = await router.create_admin_expense(
        router.AdminExpenseCreate(
            title="صيانة",
            amount=Decimal("75.00"),
            target_date=date(2026, 9, 21),
            shift_id=4,
        ),
        db=db,
        current_user=user(),
    )

    assert db.added.shift_id == 4
    assert db.added.user_id == 1
    assert result["source"] == "admin"
    assert result["shift_owner"] == db.owner.full_name
    assert result["amount"] == 75.0


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_date,wrong_role", [(True, False), (False, True)])
async def test_admin_expense_rejects_shift_from_other_day_or_non_cashier(wrong_date, wrong_role):
    db = WriteDB()
    if wrong_date:
        db.shift.target_date = date(2026, 9, 20)
    if wrong_role:
        db.owner.role = UserRole.DELIVERY
    with pytest.raises(ValidationError):
        await router.create_admin_expense(
            router.AdminExpenseCreate(title="صيانة", amount=Decimal(75), target_date=date(2026, 9, 21), shift_id=4),
            db=db,
            current_user=user(),
        )
    assert db.added is None


@pytest.mark.asyncio
async def test_admin_expense_reduces_only_selected_shifts_expected_cash(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        target = date(2026, 9, 21)
        async with sessions() as db:
            admin = User(username="expense-admin", full_name="Manager", role=UserRole.ADMIN,
                         phone="01000000101", hashed_password="test")
            first = User(username="cashier-first", full_name="Ahmed", role=UserRole.CASHIER,
                         phone="01000000102", hashed_password="test")
            second = User(username="cashier-second", full_name="Mohamed", role=UserRole.CASHIER,
                          phone="01000000103", hashed_password="test")
            db.add_all([admin, first, second])
            await db.flush()
            first_shift = CashierShift(user_id=first.id, target_date=target, opening_cash=Decimal(100),
                                       start_time=datetime(2026, 9, 21, 8, tzinfo=UTC),
                                       end_time=datetime(2026, 9, 21, 12, tzinfo=UTC))
            second_shift = CashierShift(user_id=second.id, target_date=target, opening_cash=Decimal(100),
                                        start_time=datetime(2026, 9, 21, 12, tzinfo=UTC),
                                        end_time=None)
            db.add_all([first_shift, second_shift])
            await db.commit()
            first_id, second_id = first_shift.id, second_shift.id
            admin_id = admin.id

        monkeypatch.setattr("app.core.events.order_events_manager.emit", AsyncMock())
        async with sessions() as db:
            admin = await db.get(User, admin_id)
            options = await router.list_admin_expense_shifts(target_date=target, db=db, current_user=admin)
            assert [item["id"] for item in options] == [first_id, second_id]
            assert options[0]["end_time"] is not None
            assert options[1]["end_time"] is None
            saved = await router.create_admin_expense(
                router.AdminExpenseCreate(title="صيانة", amount=Decimal(25), target_date=target, shift_id=first_id),
                db=db, current_user=admin,
            )
            assert saved["shift_owner"] == "Ahmed"
            assert saved["source"] == "admin"
            report = await ShiftsService(db).get_shifts_report(target)
            by_id = {item["id"]: item for item in report}
            assert by_id[first_id]["cash_expenses"] == 25
            assert by_id[first_id]["expected_cash"] == 75
            assert by_id[second_id]["cash_expenses"] == 0
            assert by_id[second_id]["expected_cash"] == 100
            stored = await db.get(ShiftExpense, saved["id"])
            assert stored.user_id == admin_id
            assert stored.shift_id == first_id
            listed = await router.list_admin_expenses(start_date=target, end_date=target, db=db, current_user=admin)
            assert listed["items"][0]["shift_owner"] == "Ahmed"
            assert listed["items"][0]["source"] == "admin"
            monkeypatch.setattr(router, "_current_shift", AsyncMock(return_value=first_shift))
            first_cashier = await db.get(User, first.id)
            current_expenses = await router.list_current_expenses(db=db, current_user=first_cashier, redis=None)
            assert current_expenses["items"][0]["can_delete"] is False

            with pytest.raises(ValidationError):
                await router.update_admin_expense(
                    saved["id"], router.AdminExpenseUpdate(target_date=None), db=db, current_user=admin,
                )

            with pytest.raises(ValidationError):
                await router.update_admin_expense(
                    saved["id"], router.AdminExpenseUpdate(shift_id=second_id, target_date=date(2026, 9, 22)),
                    db=db, current_user=admin,
                )
            assert stored.shift_id == first_id

            moved = await router.update_admin_expense(
                saved["id"], router.AdminExpenseUpdate(shift_id=second_id), db=db, current_user=admin,
            )
            assert moved["shift_owner"] == "Mohamed"
            report = await ShiftsService(db).get_shifts_report(target)
            by_id = {item["id"]: item for item in report}
            assert by_id[first_id]["expected_cash"] == 100
            assert by_id[second_id]["expected_cash"] == 75

            await router.delete_admin_expense(saved["id"], db=db, current_user=admin)
            report = await ShiftsService(db).get_shifts_report(target)
            assert all(item["expected_cash"] == 100 for item in report)

            cashier_expense = ShiftExpense(
                shift_id=first_id, user_id=first.id, target_date=target,
                title="مشتريات", amount=Decimal(10),
            )
            db.add(cashier_expense)
            await db.commit()
            current_expenses = await router.list_current_expenses(db=db, current_user=first_cashier, redis=None)
            assert current_expenses["items"][0]["can_delete"] is True
            with pytest.raises(ValidationError):
                await router.update_admin_expense(
                    cashier_expense.id, router.AdminExpenseUpdate(shift_id=second_id),
                    db=db, current_user=admin,
                )
            assert cashier_expense.shift_id == first_id
    finally:
        await engine.dispose()


def test_admin_expenses_ui_is_registered():
    dashboard = Path("app/frontend/dashboard.html").read_text(encoding="utf-8")
    script = Path("app/frontend/js/expenses-admin.js").read_text(encoding="utf-8")

    assert 'data-page="expenses"' in dashboard
    assert 'id="page-expenses"' in dashboard
    assert "/shifts/admin/expenses" in script
    assert 'method: id ? "PATCH" : "POST"' in script
    assert 'method: "DELETE"' in script
