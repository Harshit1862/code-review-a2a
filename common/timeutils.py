"""Time helpers. Everything is stored in UTC and shown in APP_TIMEZONE."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from common.config import settings

LOCAL_TZ = ZoneInfo(settings.timezone)

PERIODS = ("today", "yesterday", "last_24_hours", "last_7_days", "this_week", "this_month")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def parse_dt(value: str) -> datetime:
    """Parse an ISO date/datetime. Naive values are treated as APP_TIMEZONE."""
    value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc)


def resolve_period(period: str) -> Tuple[datetime, datetime]:
    """Turn a named period into a (since, until) UTC range."""
    now = now_local()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        since, until = start_of_today, now
    elif period == "yesterday":
        since, until = start_of_today - timedelta(days=1), start_of_today
    elif period == "last_24_hours":
        since, until = now - timedelta(hours=24), now
    elif period == "last_7_days":
        since, until = now - timedelta(days=7), now
    elif period == "this_week":
        since, until = start_of_today - timedelta(days=start_of_today.weekday()), now
    elif period == "this_month":
        since, until = start_of_today.replace(day=1), now
    else:
        raise ValueError(f"Unknown period '{period}'. Use one of: {', '.join(PERIODS)}")
    return since.astimezone(timezone.utc), until.astimezone(timezone.utc)


def fmt_local(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z")
