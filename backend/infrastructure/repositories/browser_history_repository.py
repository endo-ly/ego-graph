"""Browser History データ取得リポジトリ。"""

import logging
from datetime import date
from typing import Any

from backend.config import R2Config
from backend.infrastructure.database import (
    BrowserHistoryQueryParams,
    DuckDBConnection,
    get_page_views,
    get_top_domains,
)

logger = logging.getLogger(__name__)


class BrowserHistoryRepository:
    """Browser History の page view データを取得する。"""

    def __init__(self, r2_config: R2Config):
        self.r2_config = r2_config

    def _run_query(
        self,
        *,
        start_date: date,
        end_date: date,
        browser: str | None,
        profile: str | None,
        limit: int,
        query_func,
        log_label: str,
    ) -> list[dict[str, Any]]:
        with DuckDBConnection(self.r2_config) as conn:
            params = BrowserHistoryQueryParams(
                conn=conn,
                bucket=self.r2_config.bucket_name,
                events_path=self.r2_config.events_path,
                start_date=start_date,
                end_date=end_date,
                r2_config=self.r2_config,
            )
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
        start_date: date,
        end_date: date,
        *,
        browser: str | None = None,
        profile: str | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """指定期間のpage view一覧を取得する。"""
        return self._run_query(
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
        start_date: date,
        end_date: date,
        *,
        browser: str | None = None,
        profile: str | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """指定期間のdomainランキングを取得する。"""
        return self._run_query(
            start_date=start_date,
            end_date=end_date,
            browser=browser,
            profile=profile,
            limit=limit,
            query_func=get_top_domains,
            log_label="top domains",
        )
