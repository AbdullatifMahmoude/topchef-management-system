from datetime import date, datetime, timedelta, timezone

BUSINESS_DAY_START_HOUR = 7
EGYPT_TZ = timezone(timedelta(hours=3))
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
