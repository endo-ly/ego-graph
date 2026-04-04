"""SQLite-backed repositories for workflow state."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from pipelines.domain.errors import (
    WorkflowDisabledError,
    WorkflowNotFoundError,
    WorkflowRunNotFoundError,
)
from pipelines.domain.schedule import TriggerSpecType, WorkflowScheduleState
from pipelines.domain.workflow import (
    QueuedReason,
    StepRun,
    StepRunStatus,
    TriggerType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _dt_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _text_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _json_to_text(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _text_to_json(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None


def _map_run(row: sqlite3.Row) -> WorkflowRun:
    return WorkflowRun(
        run_id=row["run_id"],
        workflow_id=row["workflow_id"],
        trigger_type=TriggerType(row["trigger_type"]),
        queued_reason=QueuedReason(row["queued_reason"]),
        status=WorkflowRunStatus(row["status"]),
        scheduled_at=_text_to_dt(row["scheduled_at"]),
        queued_at=_text_to_dt(row["queued_at"]) or _utc_now(),
        started_at=_text_to_dt(row["started_at"]),
        finished_at=_text_to_dt(row["finished_at"]),
        last_error_message=row["last_error_message"],
        requested_by=row["requested_by"],
        parent_run_id=row["parent_run_id"],
        result_summary=_text_to_json(row["result_summary_json"]),
    )


def _map_step_run(row: sqlite3.Row) -> StepRun:
    return StepRun(
        step_run_id=row["step_run_id"],
        run_id=row["run_id"],
        step_id=row["step_id"],
        step_name=row["step_name"],
        sequence_no=row["sequence_no"],
        attempt_no=row["attempt_no"],
        command=row["command"],
        status=StepRunStatus(row["status"]),
        started_at=_text_to_dt(row["started_at"]),
        finished_at=_text_to_dt(row["finished_at"]),
        exit_code=row["exit_code"],
        stdout_tail=row["stdout_tail"],
        stderr_tail=row["stderr_tail"],
        log_path=row["log_path"],
        result_summary=_text_to_json(row["result_summary_json"]),
    )


class WorkflowStateRepository:
    """workflow 定義・run・step・schedule の永続化を担う。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        mutex: threading.RLock | None = None,
    ) -> None:
        self._conn = conn
        self._mutex = mutex or threading.RLock()

    def register_workflows(self, workflows: dict[str, WorkflowDefinition]) -> None:
        """Python registry を DB に同期する。"""
        now_text = _dt_to_text(_utc_now())
        with self._mutex, self._conn:
            for workflow in workflows.values():
                self._conn.execute(
                    """
                    INSERT INTO workflow_definitions (
                        workflow_id,
                        name,
                        description,
                        enabled,
                        definition_version,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        definition_version = excluded.definition_version,
                        updated_at = excluded.updated_at
                    """,
                    (
                        workflow.workflow_id,
                        workflow.name,
                        workflow.description,
                        1 if workflow.enabled else 0,
                        workflow.definition_version,
                        now_text,
                        now_text,
                    ),
                )

                registered_schedule_ids: set[str] = set()
                for index, trigger in enumerate(workflow.triggers):
                    schedule_id = f"{workflow.workflow_id}:{index}"
                    registered_schedule_ids.add(schedule_id)
                    self._conn.execute(
                        """
                        INSERT INTO workflow_schedules (
                            schedule_id,
                            workflow_id,
                            trigger_type,
                            trigger_expr,
                            timezone,
                            next_run_at,
                            last_scheduled_at
                        )
                        VALUES (?, ?, ?, ?, ?, NULL, NULL)
                        ON CONFLICT(schedule_id) DO UPDATE SET
                            workflow_id = excluded.workflow_id,
                            trigger_type = excluded.trigger_type,
                            trigger_expr = excluded.trigger_expr,
                            timezone = excluded.timezone
                        """,
                        (
                            schedule_id,
                            workflow.workflow_id,
                            trigger.trigger_type.value,
                            trigger.trigger_expr,
                            trigger.timezone,
                        ),
                    )

                if registered_schedule_ids:
                    placeholders = ", ".join(["?"] * len(registered_schedule_ids))
                    self._conn.execute(
                        f"""
                        DELETE FROM workflow_schedules
                        WHERE workflow_id = ?
                          AND schedule_id NOT IN ({placeholders})
                        """,
                        (workflow.workflow_id, *sorted(registered_schedule_ids)),
                    )
                else:
                    self._conn.execute(
                        "DELETE FROM workflow_schedules WHERE workflow_id = ?",
                        (workflow.workflow_id,),
                    )

    def list_workflows(self) -> list[dict[str, Any]]:
        """workflow 一覧を返す。"""
        with self._mutex:
            rows = self._conn.execute(
                """
                SELECT
                    d.workflow_id,
                    d.name,
                    d.description,
                    d.enabled,
                    d.definition_version,
                    MIN(s.next_run_at) AS next_run_at,
                    MAX(s.last_scheduled_at) AS last_scheduled_at
                FROM workflow_definitions d
                LEFT JOIN workflow_schedules s USING (workflow_id)
                GROUP BY
                    d.workflow_id,
                    d.name,
                    d.description,
                    d.enabled,
                    d.definition_version
                ORDER BY d.workflow_id
                """
            ).fetchall()
        return [
            {
                "workflow_id": row["workflow_id"],
                "name": row["name"],
                "description": row["description"],
                "enabled": bool(row["enabled"]),
                "definition_version": row["definition_version"],
                "next_run_at": row["next_run_at"],
                "last_scheduled_at": row["last_scheduled_at"],
            }
            for row in rows
        ]

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        """workflow 詳細を返す。"""
        with self._mutex:
            row = self._conn.execute(
                """
                SELECT
                    workflow_id,
                    name,
                    description,
                    enabled,
                    definition_version
                FROM workflow_definitions
                WHERE workflow_id = ?
                """,
                (workflow_id,),
            ).fetchone()
            schedules = self._conn.execute(
                """
                SELECT
                    schedule_id,
                    trigger_type,
                    trigger_expr,
                    timezone,
                    next_run_at,
                    last_scheduled_at
                FROM workflow_schedules
                WHERE workflow_id = ?
                ORDER BY schedule_id
                """,
                (workflow_id,),
            ).fetchall()
        if row is None:
            raise WorkflowNotFoundError(f"workflow not found: {workflow_id}")
        return {
            "workflow_id": row["workflow_id"],
            "name": row["name"],
            "description": row["description"],
            "enabled": bool(row["enabled"]),
            "definition_version": row["definition_version"],
            "schedules": [
                {
                    "schedule_id": schedule["schedule_id"],
                    "trigger_type": schedule["trigger_type"],
                    "trigger_expr": schedule["trigger_expr"],
                    "timezone": schedule["timezone"],
                    "next_run_at": schedule["next_run_at"],
                    "last_scheduled_at": schedule["last_scheduled_at"],
                }
                for schedule in schedules
            ],
        }

    def set_workflow_enabled(self, workflow_id: str, enabled: bool) -> dict[str, Any]:
        """workflow の有効/無効フラグを更新する。"""
        with self._mutex, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE workflow_definitions
                SET enabled = ?,
                    updated_at = ?
                WHERE workflow_id = ?
                """,
                (
                    1 if enabled else 0,
                    _dt_to_text(_utc_now()),
                    workflow_id,
                ),
            )
        if cursor.rowcount == 0:
            raise WorkflowNotFoundError(f"workflow not found: {workflow_id}")
        return self.get_workflow(workflow_id)

    def get_schedule_states(self) -> list[WorkflowScheduleState]:
        """全 workflow schedule の状態を返す。"""
        with self._mutex:
            rows = self._conn.execute(
                """
                SELECT
                    schedule_id,
                    workflow_id,
                    trigger_type,
                    trigger_expr,
                    timezone,
                    next_run_at,
                    last_scheduled_at
                FROM workflow_schedules
                ORDER BY schedule_id
                """
            ).fetchall()
        return [
            WorkflowScheduleState(
                schedule_id=row["schedule_id"],
                workflow_id=row["workflow_id"],
                trigger_type=TriggerSpecType(row["trigger_type"]),
                trigger_expr=row["trigger_expr"],
                timezone=row["timezone"],
                next_run_at=_text_to_dt(row["next_run_at"]),
                last_scheduled_at=_text_to_dt(row["last_scheduled_at"]),
            )
            for row in rows
        ]

    def update_schedule_state(
        self,
        *,
        schedule_id: str,
        next_run_at: datetime | None,
        last_scheduled_at: datetime | None,
    ) -> None:
        """schedule の次回予定・最終発火時刻を更新する。"""
        with self._mutex, self._conn:
            self._conn.execute(
                """
                UPDATE workflow_schedules
                SET next_run_at = ?,
                    last_scheduled_at = ?
                WHERE schedule_id = ?
                """,
                (
                    _dt_to_text(next_run_at),
                    _dt_to_text(last_scheduled_at),
                    schedule_id,
                ),
            )

    def enqueue_run(
        self,
        *,
        workflow_id: str,
        trigger_type: TriggerType,
        queued_reason: QueuedReason,
        requested_by: str = "system",
        parent_run_id: str | None = None,
        scheduled_at: datetime | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        """workflow run を queued 状態で追加する。"""
        workflow = self.get_workflow(workflow_id)
        if not workflow["enabled"]:
            raise WorkflowDisabledError(f"workflow is disabled: {workflow_id}")

        now = _utc_now()
        run_id = str(uuid.uuid4())
        with self._mutex, self._conn:
            self._conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id,
                    workflow_id,
                    trigger_type,
                    queued_reason,
                    status,
                    scheduled_at,
                    queued_at,
                    started_at,
                    finished_at,
                    last_error_message,
                    requested_by,
                    parent_run_id,
                    result_summary_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    trigger_type.value,
                    queued_reason.value,
                    WorkflowRunStatus.QUEUED.value,
                    _dt_to_text(scheduled_at),
                    _dt_to_text(now),
                    requested_by,
                    parent_run_id,
                    _json_to_text(result_summary),
                ),
            )
        return self.get_run(run_id)

    def lease_next_queued_run(self) -> WorkflowRun | None:
        """queued run を1件 running に遷移させて取得する。"""
        now_text = _dt_to_text(_utc_now())
        with self._mutex, self._conn:
            row = self._conn.execute(
                """
                SELECT *
                FROM workflow_runs
                WHERE status = ?
                ORDER BY queued_at ASC
                LIMIT 1
                """,
                (WorkflowRunStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?,
                    started_at = ?
                WHERE run_id = ?
                """,
                (
                    WorkflowRunStatus.RUNNING.value,
                    now_text,
                    row["run_id"],
                ),
            )
            updated = self._conn.execute(
                "SELECT * FROM workflow_runs WHERE run_id = ?",
                (row["run_id"],),
            ).fetchone()
        return _map_run(updated)

    def get_run(self, run_id: str) -> WorkflowRun:
        """workflow run を1件取得する。"""
        with self._mutex:
            row = self._conn.execute(
                "SELECT * FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise WorkflowRunNotFoundError(f"run not found: {run_id}")
        return _map_run(row)

    def list_runs(self, workflow_id: str | None = None) -> list[WorkflowRun]:
        """workflow run 一覧を新しい順で返す。"""
        with self._mutex:
            if workflow_id:
                rows = self._conn.execute(
                    """
                    SELECT *
                    FROM workflow_runs
                    WHERE workflow_id = ?
                    ORDER BY queued_at DESC
                    """,
                    (workflow_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT *
                    FROM workflow_runs
                    ORDER BY queued_at DESC
                    """
                ).fetchall()
        return [_map_run(row) for row in rows]

    def update_run_result(
        self,
        *,
        run_id: str,
        status: WorkflowRunStatus,
        error_message: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        """run の終了状態を保存する。"""
        with self._mutex, self._conn:
            self._conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?,
                    finished_at = ?,
                    last_error_message = ?,
                    result_summary_json = COALESCE(?, result_summary_json)
                WHERE run_id = ?
                """,
                (
                    status.value,
                    _dt_to_text(_utc_now()),
                    error_message,
                    _json_to_text(result_summary),
                    run_id,
                ),
            )
        return self.get_run(run_id)

    def insert_step_run(
        self,
        *,
        run_id: str,
        step_id: str,
        step_name: str,
        sequence_no: int,
        attempt_no: int,
        command: str,
        status: StepRunStatus = StepRunStatus.QUEUED,
    ) -> StepRun:
        """step run を作成する。"""
        step_run_id = str(uuid.uuid4())
        with self._mutex, self._conn:
            self._conn.execute(
                """
                INSERT INTO step_runs (
                    step_run_id,
                    run_id,
                    step_id,
                    step_name,
                    sequence_no,
                    attempt_no,
                    command,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_run_id,
                    run_id,
                    step_id,
                    step_name,
                    sequence_no,
                    attempt_no,
                    command,
                    status.value,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM step_runs WHERE step_run_id = ?",
                (step_run_id,),
            ).fetchone()
        return _map_step_run(row)

    def set_step_running(self, step_run_id: str) -> None:
        """step run を running に遷移させる。"""
        with self._mutex, self._conn:
            self._conn.execute(
                """
                UPDATE step_runs
                SET status = ?,
                    started_at = ?
                WHERE step_run_id = ?
                """,
                (
                    StepRunStatus.RUNNING.value,
                    _dt_to_text(_utc_now()),
                    step_run_id,
                ),
            )

    def update_step_result(
        self,
        *,
        step_run_id: str,
        status: StepRunStatus,
        exit_code: int | None = None,
        stdout_tail: str | None = None,
        stderr_tail: str | None = None,
        log_path: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> StepRun:
        """step run の終了状態を保存する。"""
        with self._mutex, self._conn:
            self._conn.execute(
                """
                UPDATE step_runs
                SET status = ?,
                    finished_at = ?,
                    exit_code = ?,
                    stdout_tail = ?,
                    stderr_tail = ?,
                    log_path = ?,
                    result_summary_json = ?
                WHERE step_run_id = ?
                """,
                (
                    status.value,
                    _dt_to_text(_utc_now()),
                    exit_code,
                    stdout_tail,
                    stderr_tail,
                    log_path,
                    _json_to_text(result_summary),
                    step_run_id,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM step_runs WHERE step_run_id = ?",
                (step_run_id,),
            ).fetchone()
        return _map_step_run(row)

    def list_step_runs(self, run_id: str) -> list[StepRun]:
        """run に紐づく step run を順序付きで返す。"""
        with self._mutex:
            rows = self._conn.execute(
                """
                SELECT *
                FROM step_runs
                WHERE run_id = ?
                ORDER BY sequence_no ASC, attempt_no ASC
                """,
                (run_id,),
            ).fetchall()
        return [_map_step_run(row) for row in rows]

    def cancel_run(self, run_id: str) -> WorkflowRun:
        """queued run を canceled にする。"""
        run = self.get_run(run_id)
        if run.status == WorkflowRunStatus.QUEUED:
            return self.update_run_result(
                run_id=run_id,
                status=WorkflowRunStatus.CANCELED,
                error_message="canceled by request",
            )
        return run

    def mark_stale_running_runs_failed(self) -> int:
        """再起動後に running のまま残った run/step を failed に寄せる。"""
        now_text = _dt_to_text(_utc_now())
        with self._mutex, self._conn:
            run_rows = self._conn.execute(
                """
                SELECT run_id
                FROM workflow_runs
                WHERE status = ?
                """,
                (WorkflowRunStatus.RUNNING.value,),
            ).fetchall()
            self._conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?,
                    finished_at = ?,
                    last_error_message = COALESCE(
                        last_error_message,
                        'workflow marked failed by startup reconcile'
                    )
                WHERE status = ?
                """,
                (
                    WorkflowRunStatus.FAILED.value,
                    now_text,
                    WorkflowRunStatus.RUNNING.value,
                ),
            )
            self._conn.execute(
                """
                UPDATE step_runs
                SET status = ?,
                    finished_at = ?,
                    stderr_tail = COALESCE(
                        stderr_tail,
                        'step marked failed by startup reconcile'
                    )
                WHERE status = ?
                """,
                (
                    StepRunStatus.FAILED.value,
                    now_text,
                    StepRunStatus.RUNNING.value,
                ),
            )
        return len(run_rows)
