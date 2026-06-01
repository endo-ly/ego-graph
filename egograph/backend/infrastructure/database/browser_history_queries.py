"""Browser History データ用のSQLクエリテンプレートとヘルパー関数。"""

from typing import Any

from backend.constants import DEFAULT_PAGE_VIEWS_LIMIT, DEFAULT_TOP_DOMAINS_LIMIT
from backend.infrastructure.database.parquet_paths import build_partition_paths
from backend.infrastructure.database.query_params import QueryParams, execute_query


def _resolve_partition_paths(params: QueryParams) -> list[str]:
    return build_partition_paths(
        params.r2_config,
        data_domain="events",
        dataset_path="browser_history/page_views",
        utc_start=params.utc_start,
        utc_end=params.utc_end,
    )


def get_page_views(
    params: QueryParams,
    *,
    browser: str | None = None,
    profile: str | None = None,
    limit: int = DEFAULT_PAGE_VIEWS_LIMIT,
) -> list[dict[str, Any]]:
    """指定期間のpage view一覧を取得する。"""
    partition_paths = _resolve_partition_paths(params)
    sql = f"""
        SELECT
            page_view_id,
            started_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS started_at,
            ended_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS ended_at,
            url,
            title,
            browser,
            profile,
            transition,
            visit_span_count
        FROM read_parquet(?)
        WHERE started_at_utc::TIMESTAMP >= ? AND started_at_utc::TIMESTAMP < ?
          AND (? IS NULL OR browser = ?)
          AND (? IS NULL OR profile = ?)
        ORDER BY started_at DESC
        LIMIT ?
    """
    return execute_query(
        params.conn,
        sql,
        [
            partition_paths,
            params.utc_start,
            params.utc_end,
            browser,
            browser,
            profile,
            profile,
            limit,
        ],
    )


def get_top_domains(
    params: QueryParams,
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
            WHERE started_at_utc::TIMESTAMP >= ? AND started_at_utc::TIMESTAMP < ?
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
            params.utc_start,
            params.utc_end,
            browser,
            browser,
            profile,
            profile,
            limit,
        ],
    )
