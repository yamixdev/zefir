from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.config import config


try:
    APP_TZ = ZoneInfo(config.app_timezone)
except ZoneInfoNotFoundError:
    APP_TZ = ZoneInfo("Europe/Moscow")


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_msk() -> datetime:
    return now_utc().astimezone(APP_TZ)


def today_msk() -> date:
    return now_msk().date()


def to_msk(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(APP_TZ)


def format_msk(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    local = to_msk(value)
    return local.strftime(fmt) if local else "без даты"


def next_msk_midnight() -> datetime:
    local = now_msk()
    next_day = local.date() + timedelta(days=1)
    return datetime.combine(next_day, time.min, tzinfo=APP_TZ)


def current_shop_rotation() -> dict:
    hours = max(1, int(config.shop_rotation_hours))
    local = now_msk()
    slot_hour = local.hour - (local.hour % hours)
    starts_at = local.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
    ends_at = starts_at + timedelta(hours=hours)
    key = starts_at.strftime("%Y%m%d%H")
    return {"key": key, "starts_at": starts_at, "ends_at": ends_at}


def msk_date_sql() -> str:
    return f"(NOW() AT TIME ZONE '{config.app_timezone}')::date"
