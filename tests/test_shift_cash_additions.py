from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError, ValidationError
from app.modules.shifts.router import CashAdditionCreate, create_shift_cash_addition


def test_cash_addition_requires_positive_amount_and_reason():
    with pytest.raises(PydanticValidationError):
        CashAdditionCreate(amount=0, reason="تم العثور على المبلغ")
    with pytest.raises(PydanticValidationError):
        CashAdditionCreate(amount=10, reason="")


@pytest.mark.asyncio
async def test_cashier_cannot_add_cash_to_shift():
    db = AsyncMock()
    cashier = SimpleNamespace(id=7, role=UserRole.CASHIER)

    with pytest.raises(AuthorizationError):
        await create_shift_cash_addition(
            1,
            CashAdditionCreate(amount=Decimal("10"), reason="تم العثور على المبلغ"),
            db,
            cashier,
        )

    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_cannot_add_cash_before_shift_is_closed():
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(
        id=1,
        end_time=None,
        actual_closing_cash=Decimal("90"),
    )
    admin = SimpleNamespace(id=2, role=UserRole.ADMIN)

    with pytest.raises(ValidationError):
        await create_shift_cash_addition(
            1,
            CashAdditionCreate(amount=Decimal("10"), reason="تم العثور على المبلغ"),
            db,
            admin,
        )

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_addition_keeps_audit_fields_and_returns_adjusted_cash():
    shift = SimpleNamespace(
        id=1,
        end_time=datetime.now(UTC),
        actual_closing_cash=Decimal("90"),
    )
    db = AsyncMock()
    db.add = Mock()
    db.scalar.side_effect = [shift, Decimal("10")]
    db.refresh.side_effect = lambda addition: (
        setattr(addition, "id", 5),
        setattr(addition, "created_at", datetime(2026, 9, 16, 20, 0, tzinfo=UTC)),
    )
    admin = SimpleNamespace(id=2, role=UserRole.ADMIN)

    result = await create_shift_cash_addition(
        1,
        CashAdditionCreate(amount=Decimal("10"), reason="  تم العثور على المبلغ  "),
        db,
        admin,
    )

    addition = db.add.call_args.args[0]
    assert addition.shift_id == 1
    assert addition.admin_id == 2
    assert addition.reason == "تم العثور على المبلغ"
    assert result["adjusted_closing_cash"] == 100
    db.commit.assert_awaited_once()
