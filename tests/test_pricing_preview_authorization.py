from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.core.enums import OrderSource, OrderType, UserRole
from app.core.exceptions import ValidationError
from app.modules.pricing.router import get_price_preview
from app.modules.pricing.schemas import PricingItem, PricingRequest, PricingResult
from app.modules.users.schemas import UserResponse


def _request(customer_phone: str) -> PricingRequest:
    return PricingRequest(
        items=[PricingItem(product_id=1, quantity=1, unit_price=Decimal("50"))],
        order_type=OrderType.DELIVERY,
        source=OrderSource.CASHIER,
        delivery_fee=Decimal("10"),
        customer_phone=customer_phone,
    )


@pytest.mark.asyncio
async def test_cashier_can_preview_delivery_for_customer_phone():
    pricing_service = AsyncMock()
    pricing_service.calculate_price.return_value = PricingResult(
        subtotal=Decimal("50"),
        discount_amount=Decimal("0"),
        delivery_fee=Decimal("10"),
        total_amount=Decimal("60"),
    )
    cashier = UserResponse(
        id=7,
        username="cashier",
        role=UserRole.CASHIER,
        phone="01000000000",
        is_active=True,
    )

    result = await get_price_preview(
        _request("01111111111"),
        pricing_service=pricing_service,
        current_user=cashier,
    )

    assert result.total_amount == Decimal("60")
    pricing_service.calculate_price.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_staff_cannot_preview_another_customers_phone():
    pricing_service = AsyncMock()
    delivery_user = UserResponse(
        id=8,
        username="rider",
        role=UserRole.DELIVERY,
        phone="01000000000",
        is_active=True,
    )

    with pytest.raises(ValidationError):
        await get_price_preview(
            _request("01111111111"),
            pricing_service=pricing_service,
            current_user=delivery_user,
        )

    pricing_service.calculate_price.assert_not_awaited()
