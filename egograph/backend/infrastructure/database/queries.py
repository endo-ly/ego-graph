"""Spotify データ用のSQLクエリテンプレートとヘルパー関数。"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from backend.config import R2Config
from backend.constants import (
    DEFAULT_SEARCH_TRACKS_LIMIT,
    DEFAULT_TOP_TRACKS_LIMIT,
    MS_TO_MINUTES_FACTOR,
)
from backend.infrastructure.database.parquet_paths import (
    build_dataset_glob,
    build_partition_paths,
)

logger = logging.getLogger(__name__)


@dataclass
class QueryParams:
    """Spotifyデータクエリ用の共通パラメータ。"""

    conn: duckdb.DuckDBPyConnection
    bucket: str
    events_path: str
    start_date: date
    end_date: date
    r2_config: R2Config | None = None


# Parquetパスパターン
SPOTIFY_PLAYS_PATH = "s3://{bucket}/{events_path}spotify/plays/**/*.parquet"
SPOTIFY_PLAYS_PARTITION_PATH = (
    "s3://{bucket}/{events_path}spotify/plays/year={year}/month={month}/**/*.parquet"
)


def get_parquet_path(bucket: str, events_path: str) -> str:
    """Spotify再生履歴のS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        events_path: イベントデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/events/spotify/plays/**/*.parquet）
    """
    return SPOTIFY_PLAYS_PATH.format(bucket=bucket, events_path=events_path)


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
        （例: ["s3://bucket/events/spotify/plays/year=2024/month=11/**/*.parquet",
              ...]）
    """
    paths: list[str] = []
    current = start_date.replace(day=1)  # 月初に正規化
    end_month = end_date.replace(day=1)

    while current <= end_month:
        path = SPOTIFY_PLAYS_PARTITION_PATH.format(
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


def _resolve_partition_paths(params: QueryParams) -> list[str]:
    if params.r2_config is not None:
        return build_partition_paths(
            params.r2_config,
            data_domain="events",
            dataset_path="spotify/plays",
            start_date=params.start_date,
            end_date=params.end_date,
        )
    return _generate_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )


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


def get_top_tracks(
    params: QueryParams, limit: int = DEFAULT_TOP_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """指定期間で最も再生された曲を取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        limit: 取得する曲数（デフォルト: 10）

    Returns:
        トップトラックのリスト（各要素は辞書）
        [
            {
                "track_name": str,
                "artist": str,
                "play_count": int,
                "total_minutes": float
            },
            ...
        ]
    """
    partition_paths = _resolve_partition_paths(params)

    query = """
        SELECT
            track_name,
            CASE
                WHEN len(artist_names) >= 1 THEN artist_names[1] ELSE NULL
            END as artist,
            COUNT(*) as play_count,
            SUM(ms_played) / ? as total_minutes
        FROM read_parquet(?)
        WHERE played_at_utc::DATE BETWEEN ? AND ?
        GROUP BY track_name, artist
        ORDER BY play_count DESC
        LIMIT ?
    """
    logger.debug(
        "Executing get_top_tracks: %s to %s, limit=%s",
        params.start_date,
        params.end_date,
        limit,
    )
    return execute_query(
        params.conn,
        query,
        [
            MS_TO_MINUTES_FACTOR,
            partition_paths,
            params.start_date,
            params.end_date,
            limit,
        ],
    )


def get_listening_stats(
    params: QueryParams, granularity: str = "day"
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
                "total_ms": int,
                "track_count": int,
                "unique_tracks": int
            },
            ...
        ]

    Raises:
        ValueError: granularityが無効な場合
    """
    partition_paths = _resolve_partition_paths(params)

    # 粒度に応じた期間フォーマットを選択
    date_format_map = {
        "day": "%Y-%m-%d",
        "week": "%G-W%V",  # ISO週番号（ISO年）
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
            strftime(played_at_utc::DATE, '{date_format}') as period,
            SUM(ms_played) as total_ms,
            COUNT(*) as track_count,
            COUNT(DISTINCT track_id) as unique_tracks
        FROM read_parquet(?)
        WHERE played_at_utc::DATE BETWEEN ? AND ?
        GROUP BY period
        ORDER BY period ASC
    """

    logger.debug(
        "Executing get_listening_stats: %s to %s, granularity=%s",
        params.start_date,
        params.end_date,
        granularity,
    )
    return execute_query(
        params.conn, query, [partition_paths, params.start_date, params.end_date]
    )


def search_tracks_by_name(
    params: QueryParams, query: str, limit: int = DEFAULT_SEARCH_TRACKS_LIMIT
) -> list[dict[str, Any]]:
    """トラック名またはアーティスト名で検索します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス）
        query: 検索クエリ（部分一致）
        limit: 取得する結果数（デフォルト: 20）

    Returns:
        検索結果のリスト
        [
            {
                "track_name": str,
                "artist": str,
                "play_count": int,
                "last_played": str
            },
            ...
        ]
    """
    # 全期間を対象とするため、ワイルドカードパスを使用
    parquet_path = (
        build_dataset_glob(
            params.r2_config,
            data_domain="events",
            dataset_path="spotify/plays",
        )
        if params.r2_config is not None
        else get_parquet_path(params.bucket, params.events_path)
    )

    search_pattern = f"%{query}%"
    sql = """
        SELECT
            track_name,
            CASE
                WHEN len(artist_names) >= 1 THEN artist_names[1] ELSE NULL
            END as artist,
            COUNT(*) as play_count,
            MAX(played_at_utc)::VARCHAR as last_played
        FROM read_parquet(?)
        WHERE LOWER(track_name) LIKE LOWER(?)
           OR (len(artist_names) >= 1 AND LOWER(artist_names[1]) LIKE LOWER(?))
        GROUP BY track_name, artist
        ORDER BY play_count DESC
        LIMIT ?
    """

    logger.debug("Searching tracks with query: %s, limit=%s", query, limit)
    return execute_query(
        params.conn, sql, [parquet_path, search_pattern, search_pattern, limit]
    )
