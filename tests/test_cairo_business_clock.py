from datetime import UTC, date, datetime

import pytest

from app.core.business_calendar import (
    business_day_start_in_order_storage,
    get_current_business_date,
    order_time_in_cairo,
)


@pytest.mark.parametrize(('instant', 'expected'), [
    (datetime(2026, 10, 31, 4, 59, tzinfo=UTC), date(2026, 10, 30)),
    (datetime(2026, 10, 31, 5, 0, tzinfo=UTC), date(2026, 10, 31)),
    (datetime(2026, 7, 1, 3, 59, tzinfo=UTC), date(2026, 6, 30)),
    (datetime(2026, 7, 1, 4, 0, tzinfo=UTC), date(2026, 7, 1)),
])
def test_business_day_follows_seven_am_cairo(instant, expected):
    assert get_current_business_date(instant) == expected


def test_boundaries_in_legacy_order_storage_across_clock_changes():
    assert business_day_start_in_order_storage(date(2026, 10, 29)).hour == 7
    assert business_day_start_in_order_storage(date(2026, 10, 30)).hour == 8
    assert business_day_start_in_order_storage(date(2026, 4, 23)).hour == 8
    assert business_day_start_in_order_storage(date(2026, 4, 24)).hour == 7


def test_repeated_hour_is_unambiguous_when_read_from_order_storage():
    before = order_time_in_cairo(datetime(2026, 10, 29, 23, 30, tzinfo=UTC).replace(tzinfo=None))
    after = order_time_in_cairo(datetime(2026, 10, 30, 0, 30, tzinfo=UTC).replace(tzinfo=None))
    assert before.hour == after.hour == 23
    assert before.utcoffset() != after.utcoffset()
