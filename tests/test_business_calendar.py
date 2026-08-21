from datetime import date, datetime, timezone

from app.core.business_calendar import get_current_business_date, is_weekly_holiday, previous_business_date


def test_friday_is_weekly_holiday():
    assert is_weekly_holiday(date(2026, 8, 21)) is True
    assert is_weekly_holiday(date(2026, 8, 22)) is False


def test_holiday_follows_business_day_until_five_am():
    assert get_current_business_date(datetime(2026, 8, 22, 1, 59, tzinfo=timezone.utc)) == date(2026, 8, 21)
    assert get_current_business_date(datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc)) == date(2026, 8, 22)


def test_previous_business_day_skips_friday():
    assert previous_business_date(date(2026, 8, 22)) == date(2026, 8, 20)
