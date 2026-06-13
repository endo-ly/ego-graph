"""Google Health取得で使用するタイムゾーン変換。"""

from datetime import UTC, date, datetime, time
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
