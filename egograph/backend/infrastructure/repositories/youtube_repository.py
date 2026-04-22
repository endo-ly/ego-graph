"""YouTube データ取得リポジトリ。

YouTube 視聴イベントデータへのアクセスを提供します。
DuckDB を使用して R2 の Parquet ファイルから直接データを取得します。
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.config import R2Config
from backend.infrastructure.database import DuckDBConnection
from backend.infrastructure.database.youtube_queries import (
    YouTubeQueryParams,
    get_top_channels,
    get_top_videos,
    get_watch_events,
    get_watching_stats,
)

logger = logging.getLogger(__name__)


class YouTubeRepository:
    """YouTube データ取得リポジトリ。

    DuckDB を使用して YouTube 視聴イベントデータを取得します。
    R2 上の Parquet ファイルに直接クエリを発行します。
    """

    def __init__(self, r2_config: R2Config):
        """YouTubeRepository を初期化します。

        Args:
            r2_config: R2 設定
        """
        self.r2_config = r2_config

    def _execute_query(
        self,
        start_date: date,
        end_date: date,
        query_func: Callable[..., list[dict[str, Any]]],
        query_name: str,
        **query_kwargs,
    ) -> list[dict[str, Any]]:
        """共通クエリ実行ヘルパー。

        Args:
            start_date: 開始日
            end_date: 終了日
            query_func: クエリ実行関数
            query_name: ログ用クエリ名
            **query_kwargs: クエリ関数に渡す追加パラメータ

        Returns:
            クエリ結果
        """
        with DuckDBConnection(self.r2_config) as conn:
            params = YouTubeQueryParams(
                conn=conn,
                bucket=self.r2_config.bucket_name,
                events_path=self.r2_config.events_path,
                master_path=self.r2_config.master_path,
                start_date=start_date,
                end_date=end_date,
            )
            result = query_func(params, **query_kwargs)

            # クエリパラメータをログに含める
            log_params = ", ".join(
                f"{k}={v}" for k, v in query_kwargs.items() if v is not None
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
        self, start_date: date, end_date: date, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """指定期間の視聴イベントを取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            limit: 取得するイベント数（デフォルト: None = 全件）

        Returns:
            視聴イベントのリスト（watched_at_utc DESC）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        return self._execute_query(
            start_date, end_date, get_watch_events, "watch events", limit=limit
        )

    def get_watching_stats(
        self, start_date: date, end_date: date, granularity: str = "day"
    ) -> list[dict[str, Any]]:
        """指定期間の視聴統計を取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            granularity: 集計単位（"day", "week", "month"）

        Returns:
            期間別統計のリスト

        Raises:
            duckdb.Error: データベース操作に失敗した場合
            ValueError: granularityが無効な場合
        """
        return self._execute_query(
            start_date,
            end_date,
            get_watching_stats,
            "watching stats",
            granularity=granularity,
        )

    def get_top_videos(
        self, start_date: date, end_date: date, limit: int = 10
    ) -> list[dict[str, Any]]:
        """指定期間で最も視聴された動画を取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            limit: 取得する動画数（デフォルト: 10）

        Returns:
            トップ動画のリスト（視聴イベント数降順）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        return self._execute_query(
            start_date, end_date, get_top_videos, "top videos", limit=limit
        )

    def get_top_channels(
        self, start_date: date, end_date: date, limit: int = 10
    ) -> list[dict[str, Any]]:
        """指定期間で最も視聴されたチャンネルを取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            limit: 取得するチャンネル数（デフォルト: 10）

        Returns:
            トップチャンネルのリスト（視聴イベント数降順）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        return self._execute_query(
            start_date, end_date, get_top_channels, "top channels", limit=limit
        )
