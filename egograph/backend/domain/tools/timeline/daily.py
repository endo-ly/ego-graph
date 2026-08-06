"""``get_daily_timeline`` の canonical tool。

REST API と MCP Tool は同じ入力制約、同じ validation、同じ canonical response を使う。
MCP のレスポンス表示だけは、呼び出し境界で compact projection を適用する。
"""

import logging
import re
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.constants import (
    DEFAULT_GAP_MINUTES,
    DEFAULT_TIMELINE_LIMIT,
    MAX_GAP_MINUTES,
    MAX_TIMELINE_LIMIT,
    TIMELINE_SOURCES,
)
from backend.domain.models.tool import ToolBase
from backend.infrastructure.repositories.timeline_repository import (
    TimelineRepository,
)

logger = logging.getLogger(__name__)

# timezone 未指定時の既定。設計仕様「未設定時は Asia/Tokyo」に従う。
# BackendConfig.timezone は未設定だと UTC になるが、本ツールの契約としては
# 日本ベースの個人データ前提で Asia/Tokyo を既定とする。
DEFAULT_TIMELINE_TIMEZONE = ZoneInfo("Asia/Tokyo")


def resolve_default_timezone(
    config_tz: ZoneInfo | None,
    *,
    timezone_configured: bool = False,
) -> ZoneInfo:
    """Backend の TIMEZONE から Daily Timeline の既定 timezone を解決する。

    設計仕様「Backend の TIMEZONE。未設定時は Asia/Tokyo」に従い、
    TIMEZONE が明示設定されている場合は UTC も含めてその値を採用する。
    REST・MCP の両構築経路で本関数を使い、解釈を一本化する。
    """
    if config_tz is not None and timezone_configured:
        return config_tz
    return DEFAULT_TIMELINE_TIMEZONE


class GetDailyTimelineTool(ToolBase):
    """1日分の統合タイムラインを取得するツール。"""

    def __init__(
        self,
        repository: TimelineRepository,
        default_timezone: ZoneInfo | None = None,
    ) -> None:
        self.repository = repository
        self.default_timezone = default_timezone or DEFAULT_TIMELINE_TIMEZONE

    @property
    def name(self) -> str:
        return "get_daily_timeline"

    @property
    def description(self) -> str:
        return (
            "複数データソース（Spotify, YouTube, Browser History, GitHub, "
            "Google Health）の観測イベントを1日単位で時刻順に統合した"
            "タイムラインを取得します。Google Health は items には入らず"
            "daily_summaries に添付されます。MCPではmetadata、空値、"
            "UTC/localの重複、items[*].event_id、correlations[*].event_ids、"
            "gaps[*].preceded_by_event_id / followed_by_event_idを省いた"
            "compact形式で返します。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "format": "date",
                    "description": "timezone 上のローカル日付（YYYY-MM-DD）",
                },
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone。既定は Backend の TIMEZONE"
                        "（未設定時は Asia/Tokyo）"
                    ),
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "含めるデータソース一覧。省略時は全 source",
                },
                "gap_minutes": {
                    "type": ["integer", "null"],
                    "description": (
                        "この分数以上の観測欠落を gaps に返す。"
                        "0 または null は gap 検出なし（既定 120）"
                    ),
                },
                "include_correlations": {
                    "type": "boolean",
                    "description": "関連候補を correlations に返すか（既定 true）",
                },
                "include_raw_refs": {
                    "type": "boolean",
                    "description": (
                        "元 dataset と record id を raw_ref に返すか（既定 false）"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "items の最大件数（1..2000、既定 500）",
                },
            },
            "required": ["date"],
        }

    def execute(
        self,
        date: str,
        timezone: str | None = None,
        sources: list[str] | None = None,
        gap_minutes: Any = DEFAULT_GAP_MINUTES,
        include_correlations: Any = True,
        include_raw_refs: Any = False,
        limit: Any = DEFAULT_TIMELINE_LIMIT,
    ) -> dict[str, Any]:
        """1日分のタイムラインを取得する。

        Raises:
            ValueError: 入力制約を満たさない場合。
        """
        validated_date = _validate_date(date)
        validated_tz = _resolve_timezone(timezone, self.default_timezone)
        validated_sources = _validate_sources(sources)
        validated_gap = _validate_gap_minutes(gap_minutes)
        validated_limit = _validate_limit(limit)
        validated_include_correlations = _validate_bool(
            include_correlations,
            field_name="include_correlations",
        )
        validated_include_raw_refs = _validate_bool(
            include_raw_refs,
            field_name="include_raw_refs",
        )

        logger.info(
            "Executing get_daily_timeline: date=%s, tz=%s, sources=%s, "
            "gap_minutes=%s, limit=%s",
            validated_date,
            validated_tz,
            validated_sources,
            validated_gap,
            validated_limit,
        )

        return self.repository.build_daily_timeline(
            date_local=validated_date,
            timezone=validated_tz,
            sources=validated_sources,
            gap_minutes=validated_gap,
            include_correlations=validated_include_correlations,
            include_raw_refs=validated_include_raw_refs,
            limit=validated_limit,
        )


def _validate_date(value: str) -> date:
    """``YYYY-MM-DD`` 形式のローカル日付を検証する。"""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("invalid_date: expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid_date: expected YYYY-MM-DD") from exc


def _resolve_timezone(value: str | None, default: ZoneInfo) -> ZoneInfo:
    """IANA timezone を解決する。``None`` のときは default を使う。"""
    if value is None:
        return default
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("invalid_timezone: unknown timezone") from exc


def _validate_sources(sources: list[str] | None) -> set[str]:
    """``sources`` の許可値を検証し、集合として返す。``None`` は全 source。"""
    if sources is None:
        return set()
    unknown = [source for source in sources if source not in TIMELINE_SOURCES]
    if unknown:
        raise ValueError("invalid_sources: unknown source")
    return set(sources)


def _validate_gap_minutes(value: int | None) -> int | None:
    """``gap_minutes`` の範囲を検証する。``None`` は gap なし。"""
    if value is None:
        return None
    if isinstance(value, str):
        if not value:
            return None
        if not re.fullmatch(r"\d+", value):
            raise ValueError("invalid_gap_minutes: expected 0..1440")
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("invalid_gap_minutes: expected 0..1440")
    if value < 0 or value > MAX_GAP_MINUTES:
        raise ValueError("invalid_gap_minutes: expected 0..1440")
    return value


def _validate_limit(value: Any) -> int:
    """``limit`` の範囲を検証する。"""
    if isinstance(value, str):
        if not re.fullmatch(r"\d+", value):
            raise ValueError("invalid_limit: expected 1..2000")
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("invalid_limit: expected 1..2000")
    if value < 1 or value > MAX_TIMELINE_LIMIT:
        raise ValueError("invalid_limit: expected 1..2000")
    return value


def _validate_bool(value: Any, *, field_name: str) -> bool:
    """REST query / MCP args の bool 入力を同じ規則で検証する。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"invalid_{field_name}: expected boolean")
