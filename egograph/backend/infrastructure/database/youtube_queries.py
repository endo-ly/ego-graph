"""YouTube データ用のSQLクエリテンプレートとヘルパー関数。"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from backend.constants import DEFAULT_TOP_TRACKS_LIMIT

logger = logging.getLogger(__name__)


@dataclass
class YouTubeQueryParams:
    """YouTubeデータクエリ用の共通パラメータ。"""

    conn: duckdb.DuckDBPyConnection
    bucket: str
    events_path: str
    master_path: str
    start_date: date
    end_date: date


# Parquetパスパターン
YOUTUBE_WATCH_EVENTS_PATH = (
    "s3://{bucket}/{events_path}youtube/watch_events/**/*.parquet"
)
YOUTUBE_WATCH_EVENTS_PARTITION_PATH = "s3://{bucket}/{events_path}youtube/watch_events/year={year}/month={month}/**/*.parquet"
YOUTUBE_VIDEOS_PATH = "s3://{bucket}/{master_path}youtube/videos/**/*.parquet"
YOUTUBE_CHANNELS_PATH = "s3://{bucket}/{master_path}youtube/channels/**/*.parquet"


def get_watch_events_parquet_path(bucket: str, events_path: str) -> str:
    """YouTube視聴イベントのS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        events_path: イベントデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/events/youtube/watch_events/**/*.parquet）
    """
    return YOUTUBE_WATCH_EVENTS_PATH.format(bucket=bucket, events_path=events_path)



def get_videos_parquet_path(bucket: str, master_path: str) -> str:
    """YouTube動画マスターのS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        master_path: マスターデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/master/youtube/videos/**/*.parquet）
    """
    return YOUTUBE_VIDEOS_PATH.format(bucket=bucket, master_path=master_path)


def get_channels_parquet_path(bucket: str, master_path: str) -> str:
    """YouTubeチャンネルマスターのS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        master_path: マスターデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/master/youtube/channels/**/*.parquet）
    """
    return YOUTUBE_CHANNELS_PATH.format(bucket=bucket, master_path=master_path)


def _generate_partition_paths(
    bucket: str, events_path: str, start_date: date, end_date: date
) -> list[str]:
    """指定期間の月パーティションに対応するParquetパスリストを生成します。

    Args:
        bucket: R2バケット名
        events_path: イベントデータのパスプレフィックス
        start_date: 開始日
        end_date: 終了日

    Returns:
        月パーティションごとのS3パスリスト
    """
    paths: list[str] = []
    current = start_date.replace(day=1)  # 月初に正規化
    end_month = end_date.replace(day=1)

    while current <= end_month:
        path = YOUTUBE_WATCH_EVENTS_PARTITION_PATH.format(
            bucket=bucket,
            events_path=events_path,
            year=current.year,
            month=f"{current.month:02d}",
        )
        paths.append(path)

        # 次の月へ
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    logger.debug(
        "Generated %d partition paths for period %s to %s",
        len(paths),
        start_date,
        end_date,
    )
    return paths


def execute_query(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    """SQLクエリを実行し、結果を辞書のリストとして返します。

    Args:
        conn: DuckDBコネクション
        sql: 実行するSQLクエリ
        params: SQLパラメータ（オプション）

    Returns:
        クエリ結果（辞書のリスト）

    Raises:
        duckdb.Error: SQLクエリ実行に失敗した場合
    """
    result = conn.execute(sql, params or [])
    df = result.df()
    return df.to_dict(orient="records")


def get_watch_events(
    params: YouTubeQueryParams, limit: int | None = None
) -> list[dict[str, Any]]:
    """指定期間の視聴イベントを取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        limit: 取得するイベント数（デフォルト: None = 全件）

    Returns:
        視聴イベントのリスト（watched_at_utc DESC）
        [
            {
                "watch_event_id": str,
                "watched_at_utc": str,
                "video_id": str,
                "video_url": str,
                "video_title": str,
                "channel_id": str,
                "channel_name": str,
                "content_type": str
            },
            ...
        ]
    """
    partition_paths = _generate_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

    query = """
        SELECT
            w.watch_event_id,
            w.watched_at_utc,
            w.video_id,
            w.video_url,
            w.video_title,
            w.channel_id,
            w.channel_name,
            w.content_type
        FROM read_parquet(?) w
        WHERE w.watched_at_utc::DATE BETWEEN ? AND ?
        ORDER BY w.watched_at_utc DESC
    """
    if limit is not None:
        query += f"\n        LIMIT {limit}"

    logger.debug(
        "Executing get_watch_events: %s to %s, limit=%s",
        params.start_date,
        params.end_date,
        limit,
    )

    return execute_query(
        params.conn,
        query,
        [partition_paths, params.start_date, params.end_date],
    )


def get_watching_stats(
    params: YouTubeQueryParams, granularity: str = "day"
) -> list[dict[str, Any]]:
    """期間別の視聴統計を取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        granularity: 集計単位（"day", "week", "month"）

    Returns:
        期間別統計のリスト
        [
            {
                "period": str,
                "watch_event_count": int,
                "unique_video_count": int,
                "unique_channel_count": int
            },
            ...
        ]

    Raises:
        ValueError: granularityが無効な場合
    """
    partition_paths = _generate_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

    # 粒度に応じた期間フォーマットを選択
    date_format_map = {
        "day": "%Y-%m-%d",
        "week": "%Y-W%V",  # ISO週番号
        "month": "%Y-%m",
    }

    if granularity not in date_format_map:
        allowed = list(date_format_map.keys())
        raise ValueError(
            f"Invalid granularity: {granularity}. Must be one of {allowed}"
        )

    date_format = date_format_map[granularity]

    # DuckDBのstrftimeフォーマット文字列は動的に埋める必要があるため
    # 例外的にf-stringを使用
    query = f"""
        SELECT
            strftime(w.watched_at_utc::DATE, '{date_format}') as period,
            COUNT(*) as watch_event_count,
            COUNT(DISTINCT w.video_id) as unique_video_count,
            COUNT(DISTINCT w.channel_id) as unique_channel_count
        FROM read_parquet(?) w
        WHERE w.watched_at_utc::DATE BETWEEN ? AND ?
        GROUP BY period
        ORDER BY period ASC
    """

    logger.debug(
        "Executing get_watching_stats: %s to %s, granularity=%s",
        params.start_date,
        params.end_date,
        granularity,
    )

    return execute_query(
        params.conn,
        query,
        [partition_paths, params.start_date, params.end_date],
    )


def get_top_videos(
    params: YouTubeQueryParams, limit: int = DEFAULT_TOP_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """指定期間で最も視聴された動画を取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        limit: 取得する動画数（デフォルト: 10）

    Returns:
        トップ動画のリスト（視聴イベント数降順）
        [
            {
                "video_id": str,
                "video_title": str,
                "channel_id": str,
                "channel_name": str,
                "watch_event_count": int
            },
            ...
        ]
    """
    partition_paths = _generate_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

    query = """
        SELECT
            w.video_id,
            w.video_title,
            w.channel_id,
            w.channel_name,
            COUNT(*) as watch_event_count
        FROM read_parquet(?) w
        WHERE w.watched_at_utc::DATE BETWEEN ? AND ?
        GROUP BY w.video_id, w.video_title, w.channel_id, w.channel_name
        ORDER BY watch_event_count DESC
        LIMIT ?
    """

    logger.debug(
        "Executing get_top_videos: %s to %s, limit=%s",
        params.start_date,
        params.end_date,
        limit,
    )

    return execute_query(
        params.conn,
        query,
        [partition_paths, params.start_date, params.end_date, limit],
    )


def get_top_channels(
    params: YouTubeQueryParams, limit: int = DEFAULT_TOP_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """指定期間で最も視聴されたチャンネルを取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        limit: 取得するチャンネル数（デフォルト: 10）

    Returns:
        トップチャンネルのリスト（視聴イベント数降順）
        [
            {
                "channel_id": str,
                "channel_name": str,
                "watch_event_count": int,
                "unique_video_count": int
            },
            ...
        ]
    """
    partition_paths = _generate_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

    query = """
        SELECT
            w.channel_id,
            w.channel_name,
            COUNT(*) as watch_event_count,
            COUNT(DISTINCT w.video_id) as unique_video_count
        FROM read_parquet(?) w
        WHERE w.watched_at_utc::DATE BETWEEN ? AND ?
        GROUP BY w.channel_id, w.channel_name
        ORDER BY watch_event_count DESC
        LIMIT ?
    """

    logger.debug(
        "Executing get_top_channels: %s to %s, limit=%s",
        params.start_date,
        params.end_date,
        limit,
    )

    return execute_query(
        params.conn,
        query,
        [partition_paths, params.start_date, params.end_date, limit],
    )
