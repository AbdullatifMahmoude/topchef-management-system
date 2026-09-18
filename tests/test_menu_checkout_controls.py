from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.settings.schemas import PaymentSettingsResponse
from app.modules.settings.service import SettingsService
from app.modules.offer.models import OfferUsage  # noqa: F401 - register ORM relationship
from app.modules.menu.models import Product  # noqa: F401 - register ORM relationship
from app.modules.orders.models import Order  # noqa: F401 - register ORM relationship
from app.modules.orders.service import OrderService
from app.core.enums import OrderSource, PaymentMethod
from app.core.exceptions import ValidationError
from app.modules.shifts.models import CashierShift
from app.modules.shifts.service import ShiftsService


class _Scalars:
    def __init__(self, rows): self.rows = rows
    def first(self): return self.rows[0] if self.rows else None


class _Result:
    def __init__(self, rows): self.rows = rows
    def scalars(self): return _Scalars(self.rows)


def _payments():
    return PaymentSettingsResponse(instapay_enabled=False, instapay_account="",
                                   wallet_enabled=False, wallet_number="",
                                   payment_account_name="")


@pytest.mark.asyncio
@pytest.mark.parametrize("active,manual,reason", [(0, True, "closed"), (1, False, "busy"), (1, True, "open")])
async def test_checkout_reason_distinguishes_shift_and_manual_pause(monkeypatch, active, manual, reason):
    db = AsyncMock()
    db.scalar.return_value = active
    service = SettingsService(db)
    service.get_payment_settings = AsyncMock(return_value=_payments())
    service.get_web_orders_status = AsyncMock(return_value=manual)
    service.get_whatsapp_settings = AsyncMock(return_value=SimpleNamespace(business_phone_number="201000000000"))
    monkeypatch.setattr("app.core.business_calendar.is_weekly_holiday", lambda: False)
    result = await service.get_menu_checkout_settings()
    assert result.ordering_reason == reason
    assert result.ordering_enabled is (reason == "open")


@pytest.mark.asyncio
async def test_first_cashier_shift_opens_web_orders(monkeypatch):
    db = AsyncMock()
    db.scalar.side_effect = [0, None]
    db.execute.return_value = _Result([])
    db.add = Mock()
    toggle = AsyncMock()
    monkeypatch.setattr(SettingsService, "toggle_web_orders", toggle)
    created = await ShiftsService(db).start_shift(7, sync_web_orders=True)
    assert isinstance(created, CashierShift)
    toggle.assert_awaited_once_with(True)


@pytest.mark.asyncio
async def test_last_cashier_logout_closes_web_orders(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = _Result([SimpleNamespace(end_time=None)])
    db.scalar.return_value = 0
    toggle = AsyncMock()
    monkeypatch.setattr(SettingsService, "toggle_web_orders", toggle)
    await ShiftsService(db).end_shift(7, sync_web_orders=True)
    toggle.assert_awaited_once_with(False)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,flag", [(PaymentMethod.INSTAPAY, "instapay_enabled"), (PaymentMethod.WALLET, "wallet_enabled")])
async def test_online_order_cannot_bypass_disabled_payment_method(method, flag):
    db = AsyncMock()
    db.in_transaction = Mock(return_value=True)
    service = OrderService(db, pricing_service=AsyncMock(), offer_service=AsyncMock())
    checkout = SimpleNamespace(ordering_enabled=True, ordering_message="", instapay_enabled=True, wallet_enabled=True)
    setattr(checkout, flag, False)
    service.settings_service.get_menu_checkout_settings = AsyncMock(return_value=checkout)
    order_data = SimpleNamespace(source=OrderSource.ONLINE, payment_method=method)
    with pytest.raises(ValidationError):
        await service._create_order_inner(order_data)
