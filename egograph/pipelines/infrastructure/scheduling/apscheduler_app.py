"""APScheduler orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pipelines.domain.schedule import MisfirePolicy, TriggerSpec, TriggerSpecType
from pipelines.domain.workflow import QueuedReason, TriggerType, WorkflowDefinition
from pipelines.infrastructure.db.repositories import WorkflowStateRepository


class ScheduleTriggerApp:
    """APScheduler job と workflow queue を接続する。"""

    def __init__(
        self,
        *,
        repository: WorkflowStateRepository,
        workflows: dict[str, WorkflowDefinition],
        timezone: str,
    ) -> None:
        self._repository = repository
        self._workflows = workflows
        self._scheduler = BackgroundScheduler(timezone=ZoneInfo(timezone))

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
        self._repository.register_workflows(self._workflows)
        for job in self._scheduler.get_jobs():
            self._scheduler.remove_job(job.id)

        schedule_states = {
            schedule.schedule_id: schedule
            for schedule in self._repository.get_schedule_states()
        }
        now = datetime.now(tz=UTC)
        for workflow in self._workflows.values():
            for index, trigger_spec in enumerate(workflow.triggers):
                schedule_id = f"{workflow.workflow_id}:{index}"
                workflow_state = self._repository.get_workflow(workflow.workflow_id)
                if not workflow_state["enabled"]:
                    self._repository.update_schedule_state(
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
                    self._repository.enqueue_run(
                        workflow_id=workflow.workflow_id,
                        trigger_type=TriggerType.RECONCILE,
                        queued_reason=QueuedReason.STARTUP_RECONCILE,
                        requested_by="system",
                        scheduled_at=state.next_run_at,
                    )

                next_run_at = trigger.get_next_fire_time(None, now)
                self._repository.update_schedule_state(
                    schedule_id=schedule_id,
                    next_run_at=next_run_at,
                    last_scheduled_at=state.last_scheduled_at if state else None,
                )
                self._scheduler.add_job(
                    self._enqueue_schedule_run,
                    id=schedule_id,
                    trigger=trigger,
                    args=[schedule_id, workflow.workflow_id],
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
        return self._repository.enqueue_run(
            workflow_id=workflow_id,
            trigger_type=TriggerType.EVENT,
            queued_reason=QueuedReason.EVENT_ENQUEUE,
            requested_by=requested_by,
            scheduled_at=datetime.now(tz=UTC),
            result_summary=result_summary,
        )

    def _enqueue_schedule_run(self, schedule_id: str, workflow_id: str) -> None:
        now = datetime.now(tz=UTC)
        self._repository.enqueue_run(
            workflow_id=workflow_id,
            trigger_type=TriggerType.SCHEDULE,
            queued_reason=QueuedReason.SCHEDULE_TICK,
            requested_by="system",
            scheduled_at=now,
        )
        job = self._scheduler.get_job(schedule_id)
        self._repository.update_schedule_state(
            schedule_id=schedule_id,
            next_run_at=job.next_run_time if job else None,
            last_scheduled_at=now,
        )

    @staticmethod
    def _build_trigger(trigger_spec: TriggerSpec):
        timezone = ZoneInfo(trigger_spec.timezone)
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
