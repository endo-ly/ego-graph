"""Spotify 再生統計ツール。

指定期間の再生統計とトップトラックを取得するツールを提供します。
"""

import logging
from typing import Any

from backend.constants import DEFAULT_TOP_TRACKS_LIMIT, MAX_LIMIT
from backend.domain.models.tool import ToolBase
from backend.infrastructure.database.connection import DuckDBConnection
from backend.infrastructure.repositories import SpotifyRepository
from backend.validators import (
    validate_date_range,
    validate_granularity,
    validate_limit,
)

logger = logging.getLogger(__name__)


class GetTopTracksTool(ToolBase):
    """指定期間で最も再生された曲を取得するツール。"""

    def __init__(self, repository: SpotifyRepository):
        """GetTopTracksTool を初期化します。

        Args:
            repository: Spotify データリポジトリ
        """
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_top_tracks"

    @property
    def description(self) -> str:
        return (
            "Spotifyの指定した期間（start_date から end_date）で"
            "最も再生された曲を取得します。再生回数の多い順にソートされます。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
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
                "limit": {
                    "type": "integer",
                    "description": "取得する曲数",
                    "default": DEFAULT_TOP_TRACKS_LIMIT,
                },
            },
            "required": ["start_date", "end_date"],
        }

    def execute(
        self, start_date: str, end_date: str, limit: int = DEFAULT_TOP_TRACKS_LIMIT
    ) -> list[dict[str, Any]]:
        """トップトラックを取得します。

        Args:
            start_date: 開始日（ISO形式: YYYY-MM-DD）
            end_date: 終了日（ISO形式: YYYY-MM-DD）
            limit: 取得する曲数

        Returns:
            トップトラックのリスト

        Raises:
            ValueError: 日付形式が不正な場合
        """
        # バリデーション（ビジネスロジック）
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)

        logger.info(
            "Executing get_top_tracks: %s to %s, limit=%s", start, end, validated_limit
        )

        with DuckDBConnection(self.repository.r2_config) as conn:
            return self.repository.get_top_tracks(conn, start, end, validated_limit)


class GetListeningStatsTool(ToolBase):
    """期間別の視聴統計を取得するツール。"""

    def __init__(self, repository: SpotifyRepository):
        """GetListeningStatsTool を初期化します。

        Args:
            repository: Spotify データリポジトリ
        """
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_listening_stats"

    @property
    def description(self) -> str:
        return (
            "Spotifyの指定した期間の聴取統計を取得します。"
            "日別、週別、月別で集計できます。"
            "総再生時間、再生トラック数、ユニーク曲数を返します。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
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
                "granularity": {
                    "type": "string",
                    "description": "集計単位",
                    "enum": ["day", "week", "month"],
                    "default": "day",
                },
            },
            "required": ["start_date", "end_date"],
        }

    def execute(
        self, start_date: str, end_date: str, granularity: str = "day"
    ) -> list[dict[str, Any]]:
        """視聴統計を取得します。

        Args:
            start_date: 開始日（ISO形式: YYYY-MM-DD）
            end_date: 終了日（ISO形式: YYYY-MM-DD）
            granularity: 集計単位（"day", "week", "month"）

        Returns:
            期間別統計のリスト

        Raises:
            ValueError: 日付形式または granularity が不正な場合
        """
        # バリデーション（ビジネスロジック）
        start, end = validate_date_range(start_date, end_date)
        validated_granularity = validate_granularity(granularity)

        logger.info(
            "Executing get_listening_stats: %s to %s, granularity=%s",
            start,
            end,
            granularity,
        )

        with DuckDBConnection(self.repository.r2_config) as conn:
            return self.repository.get_listening_stats(
                conn, start, end, validated_granularity
            )
