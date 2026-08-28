"""Google Health分析データ取得リポジトリ。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import R2Config
from backend.infrastructure.database import DuckDBConnection
from backend.infrastructure.database.google_health_queries import (
    GoogleHealthQueryParams,
    get_daily_metrics,
    get_daily_summary,
    get_record,
    get_sessions,
    get_timeseries_rows,
)
from backend.infrastructure.database.query_params import QueryParams
from backend.validators import to_utc_range


class GoogleHealthRepository:
    """Google Health compacted Parquetへの問い合わせを提供する。"""

    def __init__(self, r2_config: R2Config, tz: ZoneInfo | None = None) -> None:
        self.r2_config = r2_config
        self._tz = tz or ZoneInfo("UTC")

    def get_daily_summary(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """指定したローカル日付範囲の日次サマリを取得する。"""
        utc_start, utc_end = to_utc_range(start_date, end_date, self._tz)
        with DuckDBConnection(self.r2_config) as conn:
            return get_daily_summary(
                QueryParams(
                    conn=conn,
                    r2_config=self.r2_config,
                    start_date=start_date,
                    end_date=end_date,
                    utc_start=utc_start,
                    utc_end=utc_end,
                    tz_name=str(self._tz),
                )
            )

    def get_daily_metrics(
        self,
        start_date: date,
        end_date: date,
        data_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """指定したローカル日付範囲の日次Projectionを取得する。"""
        params = self._date_params(start_date, end_date)
        with DuckDBConnection(self.r2_config) as conn:
            return get_daily_metrics(
                GoogleHealthQueryParams(conn=conn, **params), data_type=data_type
            )

    def get_timeseries(
        self,
        data_type: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        """指定data typeの時系列sampleを取得する。"""
        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise ValueError("invalid_timeseries: timestamps must include timezone")
        start_utc = start_at.astimezone(timezone.utc)
        end_utc = end_at.astimezone(timezone.utc)
        start_date = start_utc.astimezone(self._tz).date()
        end_date = (end_utc - timedelta(microseconds=1)).astimezone(self._tz).date()
        params = self._date_params(start_date, end_date)
        with DuckDBConnection(self.r2_config) as conn:
            return get_timeseries_rows(
                GoogleHealthQueryParams(conn=conn, **params),
                data_type=data_type,
                start_at_utc=start_utc.replace(tzinfo=None),
                end_at_utc=end_utc.replace(tzinfo=None),
            )

    def get_sessions(
        self,
        start_date: date,
        end_date: date,
        data_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """指定したローカル日付範囲のsessionを取得する。"""
        params = self._date_params(start_date, end_date)
        with DuckDBConnection(self.r2_config) as conn:
            return get_sessions(
                GoogleHealthQueryParams(conn=conn, **params), data_type=data_type
            )

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        """record_idで完全保存recordを取得する。"""
        params = self._date_params(date(1970, 1, 1), date(1970, 1, 1))
        with DuckDBConnection(self.r2_config) as conn:
            return get_record(GoogleHealthQueryParams(conn=conn, **params), record_id)

    def _date_params(self, start_date: date, end_date: date) -> dict[str, Any]:
        utc_start, utc_end = to_utc_range(start_date, end_date, self._tz)
        return {
            "r2_config": self.r2_config,
            "start_date": start_date,
            "end_date": end_date,
            "utc_start": utc_start,
            "utc_end": utc_end,
            "tz_name": str(self._tz),
        }
