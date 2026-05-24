"""Browser History データ取得リポジトリ。"""

import logging
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from backend.config import R2Config
from backend.infrastructure.database.browser_history_queries import (
    get_page_views,
    get_top_domains,
)
from backend.infrastructure.database.query_params import QueryParams
from backend.validators import to_utc_range

logger = logging.getLogger(__name__)


class BrowserHistoryRepository:
    """Browser History の page view データを取得する。"""

    def __init__(self, r2_config: R2Config, tz: ZoneInfo | None = None):
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

    def _run_query(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        start_date: date,
        end_date: date,
        browser: str | None,
        profile: str | None,
        limit: int,
        query_func,
        log_label: str,
    ) -> list[dict[str, Any]]:
        params = self._build_params(conn, start_date, end_date)
        result = query_func(
            params,
            browser=browser,
            profile=profile,
            limit=limit,
        )
        logger.info(
            "Retrieved %s: start_date=%s, end_date=%s, browser=%s, "
            "profile=%s, limit=%s, count=%s",
            log_label,
            start_date,
            end_date,
            browser,
            profile,
            limit,
            len(result),
        )
        return result

    def get_page_views(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        *,
        browser: str | None = None,
        profile: str | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """指定期間のpage view一覧を取得する。"""
        return self._run_query(
            conn=conn,
            start_date=start_date,
            end_date=end_date,
            browser=browser,
            profile=profile,
            limit=limit,
            query_func=get_page_views,
            log_label="page views",
        )

    def get_top_domains(
        self,
        conn: duckdb.DuckDBPyConnection,
        start_date: date,
        end_date: date,
        *,
        browser: str | None = None,
        profile: str | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """指定期間のdomainランキングを取得する。"""
        return self._run_query(
            conn=conn,
            start_date=start_date,
            end_date=end_date,
            browser=browser,
            profile=profile,
            limit=limit,
            query_func=get_top_domains,
            log_label="top domains",
        )
