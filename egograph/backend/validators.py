"""Backend入力バリデーションヘルパー。"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.constants import MAX_LIMIT, MIN_LIMIT


def parse_date(value: date | str, field_name: str) -> date:
    """ISO日付またはdateを正規化する。"""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"invalid_{field_name}: {e}") from e


def validate_date_range(
    start_date: date | str, end_date: date | str
) -> tuple[date, date]:
    """日付範囲を正規化し、範囲の整合性を検証する。"""
    start = parse_date(start_date, "start_date")
    end = parse_date(end_date, "end_date")
    if start > end:
        raise ValueError("invalid_date_range: start_date must be on or before end_date")
    return start, end


def validate_limit(
    limit: Any, *, min_value: int = MIN_LIMIT, max_value: int = MAX_LIMIT
) -> int:
    """limitの範囲を検証する。"""
    if not isinstance(limit, int):
        raise ValueError("invalid_limit: must be a positive integer")
    if limit < min_value or limit > max_value:
        raise ValueError(f"invalid_limit: must be between {min_value} and {max_value}")
    return limit


def validate_granularity(granularity: str) -> str:
    """集計粒度を検証する。"""
    allowed = {"day", "week", "month"}
    if granularity not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise ValueError(f"invalid_granularity: must be one of: {allowed_list}")
    return granularity


def to_utc_range(
    start_date: date,
    end_date: date,
    tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    """日付範囲を環境TZと解釈し、UTCのnaive datetime範囲に変換する。

    start_date は環境TZの 00:00:00、
    end_date は翌日の環境TZ 00:00:00（< で比較するため）。
    返り値は naive datetime（tzinfo=None）で、Parquetの TIMESTAMP カラムと
    直接比較可能にする。

    Args:
        start_date: 開始日
        end_date: 終了日（この日を含む）
        tz: 環境タイムゾーン

    Returns:
        (utc_start, utc_end) — 両方とも naive datetime（UTC基準）

    Example:
        >>> to_utc_range(date(2026, 5, 17), date(2026, 5, 17), ZoneInfo("Asia/Tokyo"))
        (datetime(2026, 5, 16, 15, 0), datetime(2026, 5, 17, 15, 0))
    """
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz)
    end_dt = datetime(
        end_date.year, end_date.month, end_date.day, tzinfo=tz
    ) + timedelta(days=1)
    utc_start = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = end_dt.astimezone(timezone.utc).replace(tzinfo=None)
    return utc_start, utc_end
