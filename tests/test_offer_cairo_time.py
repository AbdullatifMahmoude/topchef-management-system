from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.enums import DiscountType
from app.modules.offer.schemas import OfferCreate, OfferUpdate


@pytest.mark.parametrize(("instant", "expected_hour"), [
    (datetime(2026, 7, 1, 12, tzinfo=UTC), 15),
    (datetime(2026, 10, 30, 12, tzinfo=UTC), 14),
])
def test_offer_times_use_cairo_offset_for_date(instant, expected_hour):
    create = OfferCreate(code="CAIRO", discount_type=DiscountType.PERCENTAGE,
                         discount_value=Decimal(10), valid_from=instant, valid_to=instant)
    update = OfferUpdate(valid_from=instant, valid_to=instant)
    assert create.valid_from.hour == expected_hour
    assert update.valid_to.hour == expected_hour
    assert create.valid_from.tzinfo is None
