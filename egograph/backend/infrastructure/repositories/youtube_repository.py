"""YouTube データ取得リポジトリ。

YouTube 視聴イベントデータへのアクセスを提供します。
DuckDB を使用して R2 の Parquet ファイルから直接データを取得します。
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from backend.config import R2Config
from backend.infrastructure.database.query_params import QueryParams
from backend.infrastructure.database.youtube_queries import (
    get_top_channels,
    get_top_videos,
    get_watch_events,
    get_watching_stats,
)
from backend.validators import to_utc_range

logger = logging.getLogger(__name__)


class YouTubeRepository:
    """YouTube データ取得リポジトリ。

    DuckDB を使用して YouTube 視聴イベントデータを取得します。
    R2 上の Parquet ファイルに直接クエリを発行します。
    """

    def __init__(self, r2_config: R2Config, tz: ZoneInfo | None = None):
        """YouTubeRepository を初期化します。

        Args:
            r2_config: R2 設定
            tz: クエリ時の日付解釈に使用するタイムゾーン
        """
        self.r2_config = r2_config
        self._tz = tz or ZoneInfo("UTC")

    def _build_params(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
    ) -> QueryParams:
        utc_start, utc_end = to_utc_range(start_date, end_date, self._tz)
        return QueryParams(
            conn=conn,
            r2_config=self.r2_config,
            start_date=start_date,
            end_date=end_date,
            utc_start=utc_start,
            utc_end=utc_end,
            tz_name=str(self._tz),
        )

    def _execute_fn(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        query_func: Callable[..., list[dict[str, Any]]],
        query_name: str,
        **kwargs,
    ) -> list[dict[str, Any]]:
        params = self._build_params(conn, start_date, end_date)
        result = query_func(params, **kwargs)
        log_params = ", ".join(
            f"{k}={v}" for k, v in kwargs.items() if v is not None
        )
        logger.info(
            "Retrieved %s: start_date=%s, end_date=%s, %s, count=%s",
            query_name,
            start_date,
            end_date,
            log_params,
            len(result),
        )
        return result

    def get_watch_events(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """指定期間の視聴イベントを取得します。

        Args:
            conn: DuckDB コネクション
            start_date: 開始日
            end_date: 終了日
            limit: 取得するイベント数（デフォルト: None = 全件）

        Returns:
            視聴イベントのリスト（watched_at_utc DESC）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        return self._execute_fn(
            conn, start_date, end_date, get_watch_events, "watch events", limit=limit
        )

    def get_watching_stats(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        granularity: str = "day",
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
            ValueError: granularityが無効な場合
        """
        return self._execute_fn(
            conn,
            start_date,
            end_date,
            get_watching_stats,
            "watching stats",
            granularity=granularity,
        )

    def get_top_videos(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """指定期間で最も視聴された動画を取得します。

        Args:
            conn: DuckDB コネクション
            start_date: 開始日
            end_date: 終了日
            limit: 取得する動画数（デフォルト: 10）

        Returns:
            トップ動画のリスト（視聴イベント数降順）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        return self._execute_fn(
            conn, start_date, end_date, get_top_videos, "top videos", limit=limit
        )

    def get_top_channels(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """指定期間で最も視聴されたチャンネルを取得します。

        Args:
            conn: DuckDB コネクション
            start_date: 開始日
            end_date: 終了日
            limit: 取得するチャンネル数（デフォルト: 10）

        Returns:
            トップチャンネルのリスト（視聴イベント数降順）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        return self._execute_fn(
            conn, start_date, end_date, get_top_channels, "top channels", limit=limit
        )
