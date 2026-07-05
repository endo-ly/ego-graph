"""Daily Timeline API レスポンススキーマ。

REST と MCP で同じ response shape を使うため、本スキーマは MCP 応答の
契約とも一致する。Pydantic モデルは REST の OpenAPI / 直列化検証に使う。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TimelineRange(BaseModel):
    """1日の対象範囲（local / UTC）。"""

    start_local: datetime
    end_local: datetime
    start_utc: datetime
    end_utc: datetime


class TimelineMeta(BaseModel):
    """タイムライン応答のメタ情報。"""

    item_count: int
    truncated: bool
    generated_at: str


class DailyTimelineResponse(BaseModel):
    """``GET /v1/data/timeline/daily`` のレスポンス。"""

    date: str
    timezone: str
    range: TimelineRange
    items: list[dict[str, Any]]
    correlations: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    daily_summaries: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any]
    meta: TimelineMeta

    model_config = {"extra": "allow"}
