from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BUSINESS_DAY_START_HOUR = 7
EGYPT_TZ = ZoneInfo("Africa/Cairo")
# Existing order timestamps are naive UTC+03:00, even in winter.
ORDER_STORAGE_TZ = timezone(timedelta(hours=3))
WEEKLY_HOLIDAY_WEEKDAY = 4  # Friday (Monday is 0)


def get_current_business_date(now: datetime | None = None) -> date:
    local_now = now.astimezone(EGYPT_TZ) if now else datetime.now(EGYPT_TZ)
    if local_now.hour < BUSINESS_DAY_START_HOUR:
        local_now -= timedelta(days=1)
    return local_now.date()


def business_day_start(target_date: date) -> datetime:
    """Return the local, naive start timestamp used by persisted order times."""
    return datetime.combine(target_date, datetime.min.time()).replace(
        hour=BUSINESS_DAY_START_HOUR
    )


def business_day_start_in_order_storage(target_date: date) -> datetime:
    """Represent 07:00 Cairo in the existing fixed-offset order time scale."""
    return business_day_start(target_date).replace(tzinfo=EGYPT_TZ).astimezone(ORDER_STORAGE_TZ).replace(tzinfo=None)


def order_time_in_cairo(value: datetime) -> datetime:
    """Convert a legacy order timestamp to an unambiguous Cairo instant."""
    return value.replace(tzinfo=ORDER_STORAGE_TZ).astimezone(EGYPT_TZ)


def is_weekly_holiday(target_date: date | None = None) -> bool:
    business_date = target_date or get_current_business_date()
    return business_date.weekday() == WEEKLY_HOLIDAY_WEEKDAY


def holiday_name(target_date: date | None = None) -> str | None:
    return "الجمعة - إجازة أسبوعية" if is_weekly_holiday(target_date) else None


def previous_business_date(target_date: date) -> date:
    candidate = target_date - timedelta(days=1)
    while is_weekly_holiday(candidate):
        candidate -= timedelta(days=1)
    return candidate
