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


YOUTUBE_WATCH_EVENTS_PATH = (
    "s3://{bucket}/{events_path}youtube/watch_events/**/*.parquet"
)
YOUTUBE_WATCH_EVENTS_PARTITION_PATH = "s3://{bucket}/{events_path}youtube/watch_events/year={year}/month={month}/**/*.parquet"
YOUTUBE_VIDEOS_PATH = "s3://{bucket}/{master_path}youtube/videos/**/*.parquet"
YOUTUBE_CHANNELS_PATH = "s3://{bucket}/{master_path}youtube/channels/**/*.parquet"


def get_watch_events_parquet_path(bucket: str, events_path: str) -> str:
    """YouTube視聴イベントのS3パスパターンを生成します。"""
    return YOUTUBE_WATCH_EVENTS_PATH.format(bucket=bucket, events_path=events_path)


def get_videos_parquet_path(bucket: str, master_path: str) -> str:
    """YouTube動画マスターのS3パスパターンを生成します。"""
    return YOUTUBE_VIDEOS_PATH.format(bucket=bucket, master_path=master_path)


def get_channels_parquet_path(bucket: str, master_path: str) -> str:
    """YouTubeチャンネルマスターのS3パスパターンを生成します。"""
    return YOUTUBE_CHANNELS_PATH.format(bucket=bucket, master_path=master_path)


def _generate_partition_paths(
    bucket: str, events_path: str, start_date: date, end_date: date
) -> list[str]:
    """指定期間の月パーティションに対応するParquetパスリストを生成します。"""
    paths: list[str] = []
    current = start_date.replace(day=1)
    end_month = end_date.replace(day=1)

    while current <= end_month:
        paths.append(
            YOUTUBE_WATCH_EVENTS_PARTITION_PATH.format(
                bucket=bucket,
                events_path=events_path,
                year=current.year,
                month=f"{current.month:02d}",
            )
        )
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
    """SQLクエリを実行し、結果を辞書のリストとして返します。"""
    result = conn.execute(sql, params or [])
    return result.df().to_dict(orient="records")


def _latest_master_ctes() -> str:
    return """
        latest_videos AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY video_id
                        ORDER BY updated_at DESC NULLS LAST
                    ) AS rn
                FROM read_parquet(?)
            )
            WHERE rn = 1
        ),
        latest_channels AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY channel_id
                        ORDER BY updated_at DESC NULLS LAST
                    ) AS rn
                FROM read_parquet(?)
            )
            WHERE rn = 1
        ),
        filtered_watch_events AS (
            SELECT *
            FROM read_parquet(?)
            WHERE watched_at_utc::DATE BETWEEN ? AND ?
        ),
        enriched_watch_events AS (
            SELECT
                w.watch_event_id,
                w.watched_at_utc,
                w.video_id,
                w.video_url,
                COALESCE(v.title, w.video_title) AS video_title,
                COALESCE(v.channel_id, w.channel_id) AS channel_id,
                COALESCE(
                    c.channel_name,
                    v.channel_name,
                    w.channel_name
                ) AS channel_name,
                w.content_type
            FROM filtered_watch_events w
            LEFT JOIN latest_videos v USING (video_id)
            LEFT JOIN latest_channels c
                ON COALESCE(v.channel_id, w.channel_id) = c.channel_id
        )
    """


def _base_query_params(params: YouTubeQueryParams) -> list[Any]:
    return [
        get_videos_parquet_path(params.bucket, params.master_path),
        get_channels_parquet_path(params.bucket, params.master_path),
        _generate_partition_paths(
            params.bucket, params.events_path, params.start_date, params.end_date
        ),
        params.start_date,
        params.end_date,
    ]


def get_watch_events(
    params: YouTubeQueryParams, limit: int | None = None
) -> list[dict[str, Any]]:
    """指定期間の視聴イベントを取得します。"""
    query = f"""
        WITH
        {_latest_master_ctes()}
        SELECT
            watch_event_id,
            watched_at_utc,
            video_id,
            video_url,
            video_title,
            channel_id,
            channel_name,
            content_type
        FROM enriched_watch_events
        ORDER BY watched_at_utc DESC
    """
    query_params = _base_query_params(params)
    if limit is not None:
        query += "\nLIMIT ?"
        query_params.append(limit)

    return execute_query(params.conn, query, query_params)


def get_watching_stats(
    params: YouTubeQueryParams, granularity: str = "day"
) -> list[dict[str, Any]]:
    """期間別の視聴統計を取得します。"""
    date_format_map = {
        "day": "%Y-%m-%d",
        "week": "%Y-W%V",
        "month": "%Y-%m",
    }
    if granularity not in date_format_map:
        raise ValueError(
            "Invalid granularity: "
            f"{granularity}. Must be one of {list(date_format_map)}"
        )

    query = f"""
        WITH
        {_latest_master_ctes()}
        SELECT
            strftime(watched_at_utc::DATE, '{date_format_map[granularity]}') AS period,
            COUNT(*) AS watch_event_count,
            COUNT(DISTINCT video_id) AS unique_video_count,
            COUNT(DISTINCT CASE
                WHEN channel_id IS NOT NULL THEN channel_id
            END) AS unique_channel_count
        FROM enriched_watch_events
        GROUP BY period
        ORDER BY period ASC
    """
    return execute_query(params.conn, query, _base_query_params(params))


def get_top_videos(
    params: YouTubeQueryParams, limit: int = DEFAULT_TOP_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """指定期間で最も視聴された動画を取得します。"""
    query = f"""
        WITH
        {_latest_master_ctes()}
        SELECT
            video_id,
            MAX(video_title) AS video_title,
            MAX(channel_id) AS channel_id,
            MAX(channel_name) AS channel_name,
            COUNT(*) AS watch_event_count
        FROM enriched_watch_events
        GROUP BY video_id
        ORDER BY watch_event_count DESC
        LIMIT ?
    """
    return execute_query(params.conn, query, [*_base_query_params(params), limit])


def get_top_channels(
    params: YouTubeQueryParams, limit: int = DEFAULT_TOP_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """指定期間で最も視聴されたチャンネルを取得します。"""
    query = f"""
        WITH
        {_latest_master_ctes()}
        SELECT
            channel_id,
            MAX(channel_name) AS channel_name,
            COUNT(*) AS watch_event_count,
            COUNT(DISTINCT video_id) AS unique_video_count
        FROM enriched_watch_events
        WHERE channel_id IS NOT NULL
        GROUP BY channel_id
        ORDER BY watch_event_count DESC
        LIMIT ?
    """
    return execute_query(params.conn, query, [*_base_query_params(params), limit])
