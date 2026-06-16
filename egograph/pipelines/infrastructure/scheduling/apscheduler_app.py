"""APScheduler orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pipelines.domain.errors import WorkflowDisabledError
from pipelines.domain.schedule import MisfirePolicy, TriggerSpec, TriggerSpecType
from pipelines.domain.workflow import QueuedReason, TriggerType, WorkflowDefinition
from pipelines.infrastructure.db.run_repository import RunRepository
from pipelines.infrastructure.db.schedule_state_repository import (
    ScheduleStateRepository,
)
from pipelines.infrastructure.db.workflow_repository import WorkflowRepository


class ScheduleTriggerApp:
    """APScheduler job と workflow queue を接続する。"""

    def __init__(
        self,
        *,
        workflow_repository: WorkflowRepository,
        schedule_state_repository: ScheduleStateRepository,
        run_repository: RunRepository,
        workflows: dict[str, WorkflowDefinition],
        timezone: str,
    ) -> None:
        self._workflow_repository = workflow_repository
        self._schedule_state_repository = schedule_state_repository
        self._run_repository = run_repository
        self._workflows = workflows
        self._timezone = ZoneInfo(timezone)
        self._scheduler = BackgroundScheduler(timezone=self._timezone)

    def start(self) -> None:
        """scheduler を開始する。"""
        self.sync_jobs()
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        """scheduler を停止する。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def sync_jobs(self) -> None:
        """registry と DB schedule 状態を同期して job を再登録する。"""
        self._workflow_repository.register_workflows(self._workflows)
        for job in self._scheduler.get_jobs():
            self._scheduler.remove_job(job.id)

        schedule_states = {
            schedule.schedule_id: schedule
            for schedule in self._schedule_state_repository.get_schedule_states()
        }
        now = datetime.now(tz=UTC)
        for workflow in self._workflows.values():
            for index, trigger_spec in enumerate(workflow.triggers):
                schedule_id = trigger_spec.schedule_id(workflow.workflow_id, index)
                workflow_state = self._workflow_repository.get_workflow(
                    workflow.workflow_id
                )
                if not workflow_state["enabled"]:
                    self._schedule_state_repository.update_schedule_state(
                        schedule_id=schedule_id,
                        next_run_at=None,
                        last_scheduled_at=schedule_states.get(
                            schedule_id
                        ).last_scheduled_at
                        if schedule_states.get(schedule_id)
                        else None,
                    )
                    continue
                trigger = self._build_trigger(trigger_spec)
                state = schedule_states.get(schedule_id)
                if (
                    state
                    and state.next_run_at
                    and state.next_run_at <= now
                    and workflow.misfire_policy == MisfirePolicy.COALESCE_LATEST
                ):
                    self._run_repository.enqueue_run(
                        workflow_id=workflow.workflow_id,
                        trigger_type=TriggerType.RECONCILE,
                        queued_reason=QueuedReason.STARTUP_RECONCILE,
                        requested_by="system",
                        scheduled_at=state.next_run_at,
                        result_summary=trigger_spec.result_summary,
                    )

                next_run_at = trigger.get_next_fire_time(None, now)
                self._schedule_state_repository.update_schedule_state(
                    schedule_id=schedule_id,
                    next_run_at=next_run_at,
                    last_scheduled_at=state.last_scheduled_at if state else None,
                )
                self._scheduler.add_job(
                    self._enqueue_schedule_run,
                    id=schedule_id,
                    trigger=trigger,
                    args=[
                        schedule_id,
                        workflow.workflow_id,
                        trigger_spec.result_summary,
                    ],
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=3600,
                )

    def enqueue_event_run(
        self,
        *,
        workflow_id: str,
        requested_by: str = "api",
        result_summary: dict | None = None,
    ):
        """event 由来の run を queue に積む。"""
        return self._run_repository.enqueue_run(
            workflow_id=workflow_id,
            trigger_type=TriggerType.EVENT,
            queued_reason=QueuedReason.EVENT_ENQUEUE,
            requested_by=requested_by,
            scheduled_at=datetime.now(tz=UTC),
            result_summary=result_summary,
        )

    def _enqueue_schedule_run(
        self,
        schedule_id: str,
        workflow_id: str,
        result_summary: dict | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        try:
            self._run_repository.enqueue_run(
                workflow_id=workflow_id,
                trigger_type=TriggerType.SCHEDULE,
                queued_reason=QueuedReason.SCHEDULE_TICK,
                requested_by="system",
                scheduled_at=now,
                result_summary=result_summary,
            )
        except WorkflowDisabledError:
            self._schedule_state_repository.update_schedule_state(
                schedule_id=schedule_id,
                next_run_at=None,
                last_scheduled_at=now,
            )
            return
        job = self._scheduler.get_job(schedule_id)
        self._schedule_state_repository.update_schedule_state(
            schedule_id=schedule_id,
            next_run_at=getattr(job, "next_run_time", None),
            last_scheduled_at=now,
        )

    def _build_trigger(self, trigger_spec: TriggerSpec):
        timezone = (
            self._timezone
            if trigger_spec.use_service_timezone
            else ZoneInfo(trigger_spec.timezone)
        )
        if trigger_spec.trigger_type == TriggerSpecType.CRON:
            minute, hour, day, month, day_of_week = trigger_spec.trigger_expr.split()
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=timezone,
            )
        if trigger_spec.trigger_type == TriggerSpecType.INTERVAL:
            expr = trigger_spec.trigger_expr.strip().lower()
            if expr.endswith("h"):
                return IntervalTrigger(hours=int(expr[:-1]), timezone=timezone)
            if expr.endswith("m"):
                return IntervalTrigger(minutes=int(expr[:-1]), timezone=timezone)
            if expr.endswith("s"):
                return IntervalTrigger(seconds=int(expr[:-1]), timezone=timezone)
            return IntervalTrigger(seconds=int(expr), timezone=timezone)
        raise ValueError(f"unsupported trigger type: {trigger_spec.trigger_type}")
