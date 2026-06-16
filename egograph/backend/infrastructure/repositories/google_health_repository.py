"""Google Health分析データ取得リポジトリ。"""

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import R2Config
from backend.infrastructure.database import DuckDBConnection
from backend.infrastructure.database.google_health_queries import get_daily_summary
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
