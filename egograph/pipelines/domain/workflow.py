"""Workflow definition and run state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pipelines.domain.schedule import MisfirePolicy, TriggerSpec


class StepExecutorType(StrEnum):
    """step 実行方式。"""

    SUBPROCESS = "subprocess"
    INPROCESS = "inprocess"


class TriggerType(StrEnum):
    """run 起動経路の大分類。"""

    SCHEDULE = "schedule"
    MANUAL = "manual"
    RETRY = "retry"
    EVENT = "event"
    RECONCILE = "reconcile"


class QueuedReason(StrEnum):
    """run が queue に積まれた理由。"""

    SCHEDULE_TICK = "schedule_tick"
    MANUAL_REQUEST = "manual_request"
    RETRY_REQUEST = "retry_request"
    STARTUP_RECONCILE = "startup_reconcile"
    EVENT_ENQUEUE = "event_enqueue"


class WorkflowRunStatus(StrEnum):
    """workflow run の状態。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class StepRunStatus(StrEnum):
    """step run の状態。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StepDefinition:
    """workflow step 定義。"""

    step_id: str
    step_name: str
    executor_type: StepExecutorType
    command: tuple[str, ...] = field(default_factory=tuple)
    callable_ref: str | None = None
    timeout_seconds: int = 1800
    max_attempts: int = 1
    retry_delay_seconds: float = 0.0


@dataclass(frozen=True)
class WorkflowDefinition:
    """workflow 定義の正本。"""

    workflow_id: str
    name: str
    description: str
    steps: tuple[StepDefinition, ...]
    triggers: tuple[TriggerSpec, ...] = field(default_factory=tuple)
    enabled: bool = True
    definition_version: int = 1
    concurrency_key: str | None = None
    timeout_seconds: int = 3600
    misfire_policy: MisfirePolicy = MisfirePolicy.COALESCE_LATEST

    @property
    def lock_key(self) -> str:
        """workflow 排他キー。"""
        return self.concurrency_key or self.workflow_id


@dataclass(frozen=True)
class WorkflowRun:
    """workflow run の永続状態。"""

    run_id: str
    workflow_id: str
    trigger_type: TriggerType
    queued_reason: QueuedReason
    status: WorkflowRunStatus
    scheduled_at: datetime | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error_message: str | None
    requested_by: str
    parent_run_id: str | None
    result_summary: dict[str, Any] | None


@dataclass(frozen=True)
class StepRun:
    """step run の永続状態。"""

    step_run_id: str
    run_id: str
    step_id: str
    step_name: str
    sequence_no: int
    attempt_no: int
    command: str
    status: StepRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    stdout_tail: str | None
    stderr_tail: str | None
    log_path: str | None
    result_summary: dict[str, Any] | None


@dataclass(frozen=True)
class StepExecutionResult:
    """executor から返す step 実行結果。"""

    status: StepRunStatus
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    log_path: str
    result_summary: dict[str, Any] | None
    error_message: str | None = None
