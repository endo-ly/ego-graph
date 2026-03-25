"""Browser History page view ツール。"""

import logging
from typing import Any

from backend.constants import (
    DEFAULT_PAGE_VIEWS_LIMIT,
    DEFAULT_TOP_DOMAINS_LIMIT,
    MAX_LIMIT,
)
from backend.domain.models.tool import ToolBase
from backend.infrastructure.repositories.browser_history_repository import (
    BrowserHistoryRepository,
)
from backend.validators import validate_date_range, validate_limit

logger = logging.getLogger(__name__)


class BrowserHistoryToolBase(ToolBase):
    """Browser History ツール共通処理。"""

    def __init__(self, repository: BrowserHistoryRepository):
        self.repository = repository

    def _base_input_schema(self, default_limit: int) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "開始日（ISO形式: YYYY-MM-DD）",
                },
                "end_date": {
                    "type": "string",
                    "description": "終了日（ISO形式: YYYY-MM-DD）",
                },
                "browser": {
                    "type": "string",
                    "description": "ブラウザ種別（edge/brave/chrome）",
                },
                "profile": {
                    "type": "string",
                    "description": "プロファイル名",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得件数",
                    "default": default_limit,
                },
            },
            "required": ["start_date", "end_date"],
        }

    def _validate_params(
        self,
        start_date: str,
        end_date: str,
        limit: int,
    ) -> tuple[object, object, int]:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
        return start, end, validated_limit


class GetPageViewsTool(BrowserHistoryToolBase):
    """指定期間の page view 一覧を取得するツール。"""

    @property
    def name(self) -> str:
        return "get_page_views"

    @property
    def description(self) -> str:
        return (
            "Browser historyの指定した期間のpage view一覧を取得します。"
            "started_at_utc の降順で返します。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._base_input_schema(DEFAULT_PAGE_VIEWS_LIMIT)

    def execute(
        self,
        start_date: str,
        end_date: str,
        browser: str | None = None,
        profile: str | None = None,
        limit: int = DEFAULT_PAGE_VIEWS_LIMIT,
    ) -> list[dict[str, Any]]:
        start, end, validated_limit = self._validate_params(
            start_date,
            end_date,
            limit,
        )

        logger.info(
            "Executing get_page_views: %s to %s, browser=%s, profile=%s, limit=%s",
            start,
            end,
            browser,
            profile,
            validated_limit,
        )
        return self.repository.get_page_views(
            start_date=start,
            end_date=end,
            browser=browser,
            profile=profile,
            limit=validated_limit,
        )


class GetTopDomainsTool(BrowserHistoryToolBase):
    """指定期間の top domains を取得するツール。"""

    @property
    def name(self) -> str:
        return "get_top_domains"

    @property
    def description(self) -> str:
        return (
            "Browser historyの指定した期間で閲覧の多いdomainを取得します。"
            "page view数の多い順で返します。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._base_input_schema(DEFAULT_TOP_DOMAINS_LIMIT)

    def execute(
        self,
        start_date: str,
        end_date: str,
        browser: str | None = None,
        profile: str | None = None,
        limit: int = DEFAULT_TOP_DOMAINS_LIMIT,
    ) -> list[dict[str, Any]]:
        start, end, validated_limit = self._validate_params(
            start_date,
            end_date,
            limit,
        )

        logger.info(
            "Executing get_top_domains: %s to %s, browser=%s, profile=%s, limit=%s",
            start,
            end,
            browser,
            profile,
            validated_limit,
        )
        return self.repository.get_top_domains(
            start_date=start,
            end_date=end,
            browser=browser,
            profile=profile,
            limit=validated_limit,
        )
