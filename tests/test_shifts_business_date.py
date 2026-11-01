import importlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.main  # noqa: F401 - register all ORM models before focused router tests
from app.core.business_calendar import EGYPT_TZ, get_current_business_date
from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError
from app.modules.shifts.router import get_shift_business_date


def test_before_seven_am_belongs_to_previous_business_date():
    now = datetime(2026, 9, 16, 3, 15, tzinfo=EGYPT_TZ)

    assert get_current_business_date(now).isoformat() == "2026-09-15"


@pytest.mark.asyncio
async def test_admin_business_date_endpoint_uses_business_day_boundary(monkeypatch):
    shifts_router = importlib.import_module("app.modules.shifts.router")
    monkeypatch.setattr(shifts_router, "get_business_date", lambda: datetime(2026, 9, 15, tzinfo=UTC).date())

    result = await get_shift_business_date(SimpleNamespace(role=UserRole.ADMIN))

    assert result == {"business_date": "2026-09-15"}


@pytest.mark.asyncio
async def test_cashier_cannot_read_admin_shift_business_date():
    with pytest.raises(AuthorizationError):
        await get_shift_business_date(SimpleNamespace(role=UserRole.CASHIER))


def test_admin_date_fields_use_business_date_and_stable_day_month_format():
    chart_source = Path("app/frontend/js/chart.js").read_text(encoding="utf-8")
    admin_source = Path("app/frontend/js/admin.js").read_text(encoding="utf-8")
    dashboard = Path("app/frontend/dashboard.html").read_text(encoding="utf-8")

    assert 'window.apiFetch("/shifts/business-date"' in chart_source
    assert "`${day}/${month}/${year}`" in admin_source
    assert dashboard.count('class="stable_date_input"') == 8
    for field_id in ("adminExpenseDate", "adminExpensesStart", "adminExpensesEnd"):
        assert f'id="{field_id}"' in dashboard
