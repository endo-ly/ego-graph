"""Browser History データ用のSQLクエリテンプレートとヘルパー関数。"""

from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from backend.config import R2Config
from backend.constants import DEFAULT_PAGE_VIEWS_LIMIT, DEFAULT_TOP_DOMAINS_LIMIT
from backend.infrastructure.database.parquet_paths import build_partition_paths
from backend.infrastructure.database.queries import execute_query

BROWSER_HISTORY_PAGE_VIEWS_PARTITION_PATH = (
    "s3://{bucket}/{events_path}browser_history/page_views/"
    "year={year}/month={month}/**/*.parquet"
)


@dataclass
class BrowserHistoryQueryParams:
    """Browser Historyクエリ用の共通パラメータ。"""

    conn: duckdb.DuckDBPyConnection
    bucket: str
    events_path: str
    start_date: date
    end_date: date
    r2_config: R2Config | None = None


def _generate_browser_history_partition_paths(
    bucket: str,
    events_path: str,
    start_date: date,
    end_date: date,
) -> list[str]:
    """指定期間のBrowser Historyパーティションパスを生成する。"""
    paths: list[str] = []
    current = start_date.replace(day=1)
    end_month = end_date.replace(day=1)

    while current <= end_month:
        paths.append(
            BROWSER_HISTORY_PAGE_VIEWS_PARTITION_PATH.format(
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

    return paths


def _resolve_partition_paths(params: BrowserHistoryQueryParams) -> list[str]:
    if params.r2_config is not None:
        return build_partition_paths(
            params.r2_config,
            data_domain="events",
            dataset_path="browser_history/page_views",
            start_date=params.start_date,
            end_date=params.end_date,
        )
    return _generate_browser_history_partition_paths(
        params.bucket,
        params.events_path,
        params.start_date,
        params.end_date,
    )


def get_page_views(
    params: BrowserHistoryQueryParams,
    *,
    browser: str | None = None,
    profile: str | None = None,
    limit: int = DEFAULT_PAGE_VIEWS_LIMIT,
) -> list[dict[str, Any]]:
    """指定期間のpage view一覧を取得する。"""
    partition_paths = _resolve_partition_paths(params)
    sql = """
        SELECT
            page_view_id,
            started_at_utc,
            ended_at_utc,
            url,
            title,
            browser,
            profile,
            transition,
            visit_span_count
        FROM read_parquet(?)
        WHERE started_at_utc::DATE BETWEEN ? AND ?
          AND (? IS NULL OR browser = ?)
          AND (? IS NULL OR profile = ?)
        ORDER BY started_at_utc DESC
        LIMIT ?
    """
    return execute_query(
        params.conn,
        sql,
        [
            partition_paths,
            params.start_date,
            params.end_date,
            browser,
            browser,
            profile,
            profile,
            limit,
        ],
    )


def get_top_domains(
    params: BrowserHistoryQueryParams,
    *,
    browser: str | None = None,
    profile: str | None = None,
    limit: int = DEFAULT_TOP_DOMAINS_LIMIT,
) -> list[dict[str, Any]]:
    """指定期間のdomain別ランキングを取得する。"""
    partition_paths = _resolve_partition_paths(params)
    sql = """
        WITH filtered_page_views AS (
            SELECT
                NULLIF(regexp_extract(url, '^[a-zA-Z]+://([^/?#]+)', 1), '') AS domain,
                url
            FROM read_parquet(?)
            WHERE started_at_utc::DATE BETWEEN ? AND ?
              AND (? IS NULL OR browser = ?)
              AND (? IS NULL OR profile = ?)
        )
        SELECT
            domain,
            COUNT(*) AS page_view_count,
            COUNT(DISTINCT url) AS unique_urls
        FROM filtered_page_views
        WHERE domain IS NOT NULL
        GROUP BY domain
        ORDER BY page_view_count DESC, unique_urls DESC, domain ASC
        LIMIT ?
    """
    return execute_query(
        params.conn,
        sql,
        [
            partition_paths,
            params.start_date,
            params.end_date,
            browser,
            browser,
            profile,
            profile,
            limit,
        ],
    )
