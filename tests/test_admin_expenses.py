import importlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError, ValidationError
from app.modules.customer.models import (
    CustomerAddress,  # noqa: F401 - register ORM relationship
)
from app.modules.menu.models import Product  # noqa: F401 - register ORM relationship
from app.modules.offer.models import (
    OfferUsage,  # noqa: F401 - register ORM relationship
)

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

    def add(self, value):
        self.added = value

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
    result = await router.list_admin_expenses(
        start_date=date(2026, 9, 21),
        end_date=date(2026, 9, 21),
        db=ListDB([(expense(), recorder), (expense(shift_id=4, amount="10"), recorder)]),
        current_user=recorder,
    )

    assert result["count"] == 2
    assert result["total"] == 35.5
    assert result["items"][0]["source"] == "admin"
    assert result["items"][0]["editable_date"] is True
    assert result["items"][1]["source"] == "cashier"
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
async def test_admin_created_expense_is_not_charged_to_cashier_shift(monkeypatch):
    async def totals(_db, _shift_id, _target_date):
        return Decimal(0), Decimal("75.00")

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
        ),
        db=db,
        current_user=user(),
    )

    assert db.added.shift_id is None
    assert db.added.user_id == 1
    assert result["source"] == "admin"
    assert result["amount"] == 75.0


def test_admin_expenses_ui_is_registered():
    dashboard = Path("app/frontend/dashboard.html").read_text(encoding="utf-8")
    script = Path("app/frontend/js/expenses-admin.js").read_text(encoding="utf-8")

    assert 'data-page="expenses"' in dashboard
    assert 'id="page-expenses"' in dashboard
    assert "/shifts/admin/expenses" in script
    assert 'method: id ? "PATCH" : "POST"' in script
    assert 'method: "DELETE"' in script
