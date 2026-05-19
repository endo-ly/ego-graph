"""YouTube データ用のSQLクエリテンプレートとヘルパー関数。"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import duckdb

from backend.constants import DEFAULT_TOP_TRACKS_LIMIT

logger = logging.getLogger(__name__)

DEFAULT_WATCH_EVENTS_LIMIT = 100_000


@dataclass
class YouTubeQueryParams:
    """YouTubeデータクエリ用の共通パラメータ。"""

    conn: duckdb.DuckDBPyConnection
    bucket: str
    events_path: str
    master_path: str
    start_date: date
    end_date: date
    utc_start: datetime
    utc_end: datetime
    tz_name: str = "UTC"


YOUTUBE_WATCH_EVENTS_PATH = (
    "s3://{bucket}/{events_path}youtube/watch_events/**/*.parquet"
)
YOUTUBE_WATCH_EVENTS_PARTITION_PATH = "s3://{bucket}/{events_path}youtube/watch_events/year={year}/month={month}/**/*.parquet"
YOUTUBE_VIDEOS_PATH = "s3://{bucket}/{master_path}youtube/videos/data.parquet"
YOUTUBE_CHANNELS_PATH = "s3://{bucket}/{master_path}youtube/channels/data.parquet"


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
    bucket: str, events_path: str, utc_start: datetime, utc_end: datetime
) -> list[str]:
    """指定期間の月パーティションに対応するParquetパスリストを生成します。"""
    paths: list[str] = []
    current = date(utc_start.year, utc_start.month, 1)
    end_month = date(utc_end.year, utc_end.month, 1)

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
        utc_start,
        utc_end,
    )
    return paths


def _resolve_watch_event_paths(params: YouTubeQueryParams) -> list[str]:
    """実在する月パーティションのみを返し、未作成時は全体globへフォールバックする。"""
    partition_paths = _generate_partition_paths(
        params.bucket, params.events_path, params.utc_start, params.utc_end
    )
    existing_paths: list[str] = []

    for path in partition_paths:
        try:
            matched_count = params.conn.execute(
                "SELECT COUNT(*) FROM glob(?)",
                [path],
            ).fetchone()[0]
        except duckdb.Error:
            logger.warning(
                "Failed to validate partition path with glob(); "
                "fallback to dataset glob: %s",
                path,
                exc_info=True,
            )
            return [get_watch_events_parquet_path(params.bucket, params.events_path)]
        if matched_count > 0:
            existing_paths.append(path)

    if existing_paths:
        return existing_paths

    fallback = get_watch_events_parquet_path(params.bucket, params.events_path)
    logger.debug(
        "No month partitions found for %s to %s; fallback to dataset glob: %s",
        params.start_date,
        params.end_date,
        fallback,
    )
    return [fallback]


def execute_query(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    """SQLクエリを実行し、結果を辞書のリストとして返します。"""
    result = conn.execute(sql, params or [])
    return result.df().to_dict(orient="records")


def _parquet_file_exists(conn: duckdb.DuckDBPyConnection, path: str) -> bool:
    """DuckDB glob で親ディレクトリを列挙し、対象パスの厳密一致で存在確認する。"""
    try:
        parent = path.rsplit("/", 1)[0] if "/" in path else "."
        probe_glob = f"{parent}/*"
        matched_count = conn.execute(
            "SELECT COUNT(*) FROM glob(?) WHERE file = ?",
            [probe_glob, path],
        ).fetchone()[0]
        return matched_count > 0
    except duckdb.Error:
        logger.warning("Failed to check parquet existence: %s", path, exc_info=True)
        return False


def _build_enriched_cte(
    params: YouTubeQueryParams,
) -> tuple[str, list[Any]]:
    """マスターデータの有無に応じた CTE とパラメータを構築する。

    マスター Parquet が存在しない場合は、空結果の CTE を生成し
    LEFT JOIN + COALESCE で watch events 側の値がそのまま使われるようにする。
    """
    videos_path = get_videos_parquet_path(params.bucket, params.master_path)
    channels_path = get_channels_parquet_path(params.bucket, params.master_path)

    has_videos = _parquet_file_exists(params.conn, videos_path)
    has_channels = _parquet_file_exists(params.conn, channels_path)

    ctes: list[str] = []
    sql_params: list[Any] = []

    if has_videos:
        ctes.append("latest_videos AS (SELECT * FROM read_parquet(?))")
        sql_params.append(videos_path)
    else:
        logger.debug("Video master parquet not found: %s", videos_path)
        ctes.append(
            "latest_videos AS ("
            "SELECT NULL::VARCHAR AS video_id, "
            "NULL::VARCHAR AS title, "
            "NULL::VARCHAR AS channel_id, "
            "NULL::VARCHAR AS channel_name "
            "WHERE 1=0)"
        )

    if has_channels:
        ctes.append("latest_channels AS (SELECT * FROM read_parquet(?))")
        sql_params.append(channels_path)
    else:
        logger.debug("Channel master parquet not found: %s", channels_path)
        ctes.append(
            "latest_channels AS ("
            "SELECT NULL::VARCHAR AS channel_id, "
            "NULL::VARCHAR AS channel_name "
            "WHERE 1=0)"
        )

    ctes.append(
        "filtered_watch_events AS ("
        "SELECT * FROM read_parquet(?) "
        "WHERE watched_at_utc::TIMESTAMP >= ? AND watched_at_utc::TIMESTAMP < ?)"
    )
    sql_params.extend(
        [
            _resolve_watch_event_paths(params),
            params.utc_start,
            params.utc_end,
        ]
    )

    ctes.append(
        "enriched_watch_events AS ("
        "SELECT "
        "w.watch_event_id, "
        "w.watched_at_utc, "
        "w.video_id, "
        "w.video_url, "
        "COALESCE(v.title, w.video_title) AS video_title, "
        "COALESCE(v.channel_id, w.channel_id) AS channel_id, "
        "COALESCE(c.channel_name, v.channel_name, w.channel_name) AS channel_name, "
        "w.content_type "
        "FROM filtered_watch_events w "
        "LEFT JOIN latest_videos v USING (video_id) "
        "LEFT JOIN latest_channels c "
        "ON COALESCE(v.channel_id, w.channel_id) = c.channel_id)"
    )

    return ",\n".join(ctes), sql_params


def get_watch_events(
    params: YouTubeQueryParams, limit: int | None = None
) -> list[dict[str, Any]]:
    """指定期間の視聴イベントを取得します。"""
    ctes, cte_params = _build_enriched_cte(params)
    query = f"""
        WITH
        {ctes}
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
        ORDER BY watched_at_utc::TIMESTAMP DESC
        LIMIT COALESCE(?, {DEFAULT_WATCH_EVENTS_LIMIT})
    """
    cte_params.append(limit)

    return execute_query(params.conn, query, cte_params)


def get_watching_stats(
    params: YouTubeQueryParams, granularity: str = "day"
) -> list[dict[str, Any]]:
    """期間別の視聴統計を取得します。"""
    date_format_map = {
        "day": "%Y-%m-%d",
        "week": "%G-W%V",
        "month": "%Y-%m",
    }
    if granularity not in date_format_map:
        raise ValueError(
            "Invalid granularity: "
            f"{granularity}. Must be one of {list(date_format_map)}"
        )

    ctes, cte_params = _build_enriched_cte(params)
    query = f"""
        WITH
        {ctes}
        SELECT
            strftime(
                watched_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}',
                '{date_format_map[granularity]}'
            ) AS period,
            COUNT(*) AS watch_event_count,
            COUNT(DISTINCT video_id) AS unique_video_count,
            COUNT(DISTINCT CASE
                WHEN channel_id IS NOT NULL THEN channel_id
            END) AS unique_channel_count
        FROM enriched_watch_events
        GROUP BY period
        ORDER BY period ASC
    """
    return execute_query(params.conn, query, cte_params)


def get_top_videos(
    params: YouTubeQueryParams, limit: int = DEFAULT_TOP_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """指定期間で最も視聴された動画を取得します。"""
    ctes, cte_params = _build_enriched_cte(params)
    query = f"""
        WITH
        {ctes}
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
    return execute_query(params.conn, query, [*cte_params, limit])


def get_top_channels(
    params: YouTubeQueryParams, limit: int = DEFAULT_TOP_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """指定期間で最も視聴されたチャンネルを取得します。"""
    ctes, cte_params = _build_enriched_cte(params)
    query = f"""
        WITH
        {ctes}
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
    return execute_query(params.conn, query, [*cte_params, limit])
