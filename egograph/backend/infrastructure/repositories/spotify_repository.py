"""Spotify データ取得リポジトリ。

Spotify 再生履歴データへのアクセスを提供します。
DuckDB を使用して R2 の Parquet ファイルから直接データを取得します。
"""

import logging
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from backend.config import R2Config
from backend.infrastructure.database.queries import get_listening_stats, get_top_tracks
from backend.infrastructure.database.query_params import QueryParams
from backend.validators import to_utc_range

logger = logging.getLogger(__name__)


class SpotifyRepository:
    """Spotify データ取得リポジトリ。

    DuckDB を使用して Spotify 再生履歴データを取得します。
    R2 上の Parquet ファイルに直接クエリを発行します。
    """

    def __init__(self, r2_config: R2Config, tz: ZoneInfo | None = None):
        """SpotifyRepository を初期化します。

        Args:
            r2_config: R2 設定
            tz: クエリ時の日付解釈に使用するタイムゾーン
        """
        self.r2_config = r2_config
        self._tz = tz or ZoneInfo("UTC")

    def get_top_tracks(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict[str, Any]]:
        """指定期間で最も再生された曲を取得します。

        Args:
            conn: DuckDB コネクション
            start_date: 開始日
            end_date: 終了日
            limit: 取得する曲数

        Returns:
            トップトラックのリスト（再生回数降順）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        utc_start, utc_end = to_utc_range(start_date, end_date, self._tz)
        params = QueryParams(
            conn=conn,
            r2_config=self.r2_config,
            start_date=start_date,
            end_date=end_date,
            utc_start=utc_start,
            utc_end=utc_end,
            tz_name=str(self._tz),
        )
        result = get_top_tracks(params, limit)
        logger.info(
            "Retrieved top tracks: start_date=%s, end_date=%s, limit=%s, count=%s",
            start_date,
            end_date,
            limit,
            len(result),
        )
        return result

    def get_listening_stats(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        granularity: str,
    ) -> list[dict[str, Any]]:
        """指定期間の視聴統計を取得します。

        Args:
            conn: DuckDB コネクション
            start_date: 開始日
            end_date: 終了日
            granularity: 集計単位（"day", "week", "month"）

        Returns:
            期間別統計のリスト

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        utc_start, utc_end = to_utc_range(start_date, end_date, self._tz)
        params = QueryParams(
            conn=conn,
            r2_config=self.r2_config,
            start_date=start_date,
            end_date=end_date,
            utc_start=utc_start,
            utc_end=utc_end,
            tz_name=str(self._tz),
        )
        result = get_listening_stats(params, granularity)
        logger.info(
            "Retrieved listening stats: "
            "start_date=%s, end_date=%s, granularity=%s, count=%s",
            start_date,
            end_date,
            granularity,
            len(result),
        )
        return result
