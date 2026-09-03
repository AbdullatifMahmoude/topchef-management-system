from datetime import date, datetime, timezone

from app.core.business_calendar import business_day_start, get_current_business_date, is_weekly_holiday, previous_business_date


def test_friday_is_weekly_holiday():
    assert is_weekly_holiday(date(2026, 8, 21)) is True
    assert is_weekly_holiday(date(2026, 8, 22)) is False


def test_holiday_follows_business_day_until_seven_am():
    assert get_current_business_date(datetime(2026, 8, 22, 3, 59, tzinfo=timezone.utc)) == date(2026, 8, 21)
    assert get_current_business_date(datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)) == date(2026, 8, 22)


def test_business_day_start_is_seven_am_local_naive():
    assert business_day_start(date(2026, 8, 22)) == datetime(2026, 8, 22, 7, 0)


def test_previous_business_day_skips_friday():
    assert previous_business_date(date(2026, 8, 22)) == date(2026, 8, 20)
