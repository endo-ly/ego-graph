"""Workflow definition persistence."""

from __future__ import annotations

from typing import Any

from pipelines.domain.errors import WorkflowNotFoundError
from pipelines.domain.workflow import WorkflowDefinition
from pipelines.infrastructure.db._shared import SQLiteRepository, dt_to_text, utc_now


class WorkflowRepository(SQLiteRepository):
    """workflow 定義の永続化を担う。"""

    def register_workflows(self, workflows: dict[str, WorkflowDefinition]) -> None:
        """Python registry を DB に同期する。"""
        now_text = dt_to_text(utc_now())
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
                    schedule_id = (
                        trigger.schedule_name or f"{workflow.workflow_id}:{index}"
                    )
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
                            (
                                "TIMEZONE"
                                if trigger.use_service_timezone
                                else trigger.timezone
                            ),
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
                    dt_to_text(utc_now()),
                    workflow_id,
                ),
            )
        if cursor.rowcount == 0:
            raise WorkflowNotFoundError(f"workflow not found: {workflow_id}")
        return self.get_workflow(workflow_id)
