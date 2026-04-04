"""Browser history ingest schema definitions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

BrowserName = Literal["edge", "brave", "chrome"]


class BrowserHistoryItem(BaseModel):
    """単一訪問イベントの受信スキーマ。"""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    visit_time: datetime
    title: str | None = None
    visit_id: str | None = None
    referring_visit_id: str | None = None
    transition: str | None = None


class BrowserHistoryPayload(BaseModel):
    """Browser history 同期ペイロード。"""

    model_config = ConfigDict(extra="forbid")

    sync_id: UUID
    source_device: str = Field(min_length=1)
    browser: BrowserName
    profile: str = Field(min_length=1)
    synced_at: datetime
    items: list[BrowserHistoryItem]


class BrowserHistoryIngestState(BaseModel):
    """source_device/browser/profile ごとの最新同期状態。"""

    model_config = ConfigDict(extra="forbid")

    sync_id: str
    last_successful_sync_at: datetime
    last_sync_status: Literal["events_saved"]
    last_failure_code: str | None = None
    last_received_at: datetime
    last_accepted_count: int = Field(ge=0)
