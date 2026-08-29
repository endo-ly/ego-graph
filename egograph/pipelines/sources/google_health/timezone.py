"""Google Health取得で使用するタイムゾーン変換。"""

from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo


def local_date_start_utc(value: date, timezone: ZoneInfo) -> datetime:
    """ローカル日付の開始時刻をUTCへ変換する。"""
    return datetime.combine(value, time.min, tzinfo=timezone).astimezone(UTC)


def local_date_start_rfc3339(value: date, timezone: ZoneInfo) -> str:
    """ローカル日付の開始時刻をUTCのRFC 3339文字列で返す。"""
    return local_date_start_utc(value, timezone).isoformat().replace("+00:00", "Z")


def local_date(value: datetime, timezone: ZoneInfo) -> date:
    """絶対時刻を設定タイムゾーンの日付へ変換する。"""
    return value.astimezone(timezone).date()


def projection_row_local_date(
    dataset_name: str,
    row: dict[str, Any],
    timezone: ZoneInfo,
) -> date:
    """Projection rowのrange replace対象日を返す。"""
    if dataset_name == "sessions":
        column = (
            "ended_at_utc"
            if row.get("data_type") == "sleep"
            else "started_at_utc"
        )
    else:
        column = {
            "records": "record_date",
            "daily_metrics": "date",
            "samples": "measured_at_utc",
            "intervals": "started_at_utc",
        }[dataset_name]

    value = row[column]
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    timestamp = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return local_date(timestamp, timezone)
