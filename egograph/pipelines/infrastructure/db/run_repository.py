"""Workflow run persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pipelines.domain.errors import (
    WorkflowDisabledError,
    WorkflowRunNotFoundError,
)
from pipelines.domain.workflow import (
    QueuedReason,
    StepRunStatus,
    TriggerType,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.infrastructure.db._shared import (
    SQLiteRepository,
    dt_to_text,
    json_to_text,
    map_run,
    utc_now,
)
from pipelines.infrastructure.db.workflow_repository import WorkflowRepository


class RunRepository(SQLiteRepository):
    """workflow run の永続化を担う。"""

    def __init__(
        self,
        workflow_repository: WorkflowRepository,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._workflow_repository = workflow_repository

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
        workflow = self._workflow_repository.get_workflow(workflow_id)
        if not workflow["enabled"]:
            raise WorkflowDisabledError(f"workflow is disabled: {workflow_id}")

        now = utc_now()
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
                    dt_to_text(scheduled_at),
                    dt_to_text(now),
                    requested_by,
                    parent_run_id,
                    json_to_text(result_summary),
                ),
            )
        return self.get_run(run_id)

    def lease_next_queued_run(self) -> WorkflowRun | None:
        """queued run を1件 running に遷移させて取得する。"""
        now_text = dt_to_text(utc_now())
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
        return map_run(updated)

    def requeue_run(self, run_id: str, *, reason: str | None = None) -> WorkflowRun:
        """running に遷移させた run を再度 queued に戻す。"""
        now_text = dt_to_text(utc_now())
        with self._mutex, self._conn:
            self._conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?,
                    queued_at = ?,
                    started_at = NULL,
                    last_error_message = ?
                WHERE run_id = ?
                """,
                (
                    WorkflowRunStatus.QUEUED.value,
                    now_text,
                    reason,
                    run_id,
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> WorkflowRun:
        """workflow run を1件取得する。"""
        with self._mutex:
            row = self._conn.execute(
                "SELECT * FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise WorkflowRunNotFoundError(f"run not found: {run_id}")
        return map_run(row)

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
        return [map_run(row) for row in rows]

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
                    dt_to_text(utc_now()),
                    error_message,
                    json_to_text(result_summary),
                    run_id,
                ),
            )
        return self.get_run(run_id)

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
        now_text = dt_to_text(utc_now())
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
