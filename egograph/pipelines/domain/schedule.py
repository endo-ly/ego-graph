"""Workflow schedule definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class TriggerSpecType(StrEnum):
    """スケジュール種別。"""

    CRON = "cron"
    INTERVAL = "interval"


class MisfirePolicy(StrEnum):
    """起動漏れ収束ポリシー。"""

    COALESCE_LATEST = "coalesce_latest"
    SKIP_MISFIRE = "skip_misfire"


@dataclass(frozen=True)
class TriggerSpec:
    """APScheduler trigger の宣言。"""

    trigger_type: TriggerSpecType
    trigger_expr: str
    timezone: str = "UTC"
    schedule_name: str | None = None
    result_summary: dict[str, Any] | None = None
    use_service_timezone: bool = False


@dataclass(frozen=True)
class WorkflowScheduleState:
    """workflow_schedules の永続状態。"""

    schedule_id: str
    workflow_id: str
    trigger_type: TriggerSpecType
    trigger_expr: str
    timezone: str
    next_run_at: datetime | None
    last_scheduled_at: datetime | None
