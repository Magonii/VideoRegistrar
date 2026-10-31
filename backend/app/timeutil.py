"""Время в БД хранится как naive UTC; наружу отдаётся ISO с суффиксом Z."""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from pydantic import AfterValidator, PlainSerializer

from .config import MALL_TZ


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def norm_utc(dt: datetime) -> datetime:
    """aware -> naive UTC; naive считаем уже UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def to_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(MALL_TZ)


def from_local(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def local_day_start_utc(dt_utc: datetime) -> datetime:
    loc = to_local(dt_utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return from_local(loc)


def day_start_n_days_ago(now_utc: datetime, days: int) -> datetime:
    loc = to_local(now_utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return from_local(loc - timedelta(days=days))


def iso(dt: datetime) -> str:
    return norm_utc(dt).isoformat(timespec="seconds") + "Z"


UtcDateTime = Annotated[
    datetime,
    AfterValidator(norm_utc),
    PlainSerializer(iso, return_type=str),
]
