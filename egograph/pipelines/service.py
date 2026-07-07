"""Pipelines application service composition."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import SecretStr

from pipelines.config import PipelinesConfig
from pipelines.domain.errors import WorkflowNotFoundError
from pipelines.domain.workflow import QueuedReason, TriggerType, WorkflowRun
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.run_repository import RunRepository
from pipelines.infrastructure.db.schedule_state_repository import (
    ScheduleStateRepository,
)
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.infrastructure.db.step_run_repository import StepRunRepository
from pipelines.infrastructure.db.workflow_repository import WorkflowRepository
from pipelines.infrastructure.dispatching.lock_manager import WorkflowLockManager
from pipelines.infrastructure.dispatching.run_dispatcher import RunDispatcher
from pipelines.infrastructure.execution.inprocess_executor import InProcessStepExecutor
from pipelines.infrastructure.execution.log_store import LocalLogStore
from pipelines.infrastructure.execution.subprocess_executor import (
    SubprocessStepExecutor,
)
from pipelines.infrastructure.notification.service import NotificationService
from pipelines.infrastructure.scheduling.apscheduler_app import ScheduleTriggerApp
from pipelines.sources.google_health.auth import GoogleHealthAuth
from pipelines.sources.google_health.client import GoogleHealthAPIClient
from pipelines.sources.google_health.repository import GoogleHealthRepository
from pipelines.sources.google_health.token_cipher import TokenCipher
from pipelines.workflows.registry import get_workflows


@dataclass
class PipelineService:
    """pipelines サービスのユースケース境界。"""

    config: PipelinesConfig
    workflow_repository: WorkflowRepository
    schedule_state_repository: ScheduleStateRepository
    run_repository: RunRepository
    step_run_repository: StepRunRepository
    lock_manager: WorkflowLockManager
    scheduler: ScheduleTriggerApp
    dispatcher: RunDispatcher
    log_store: LocalLogStore
    google_health_repository: GoogleHealthRepository
    google_health_auth: GoogleHealthAuth | None
    google_health_client: GoogleHealthAPIClient | None

    @classmethod
    def create(cls, config: PipelinesConfig | None = None) -> "PipelineService":
        """設定と adapters を組み立てる。"""
        config = config or PipelinesConfig()
        conn = connect(config.database_path)
        initialize_schema(conn)
        workflows = get_workflows()
        db_mutex = threading.RLock()
        workflow_repository = WorkflowRepository(conn, mutex=db_mutex)
        schedule_state_repository = ScheduleStateRepository(conn, mutex=db_mutex)
        run_repository = RunRepository(
            workflow_repository,
            conn,
            mutex=db_mutex,
        )
        step_run_repository = StepRunRepository(conn, mutex=db_mutex)
        lock_manager = WorkflowLockManager(
            conn,
            config.lock_lease_seconds,
            mutex=db_mutex,
        )
        log_store = LocalLogStore(config.logs_root)
        notification_service = NotificationService(
            webhook_url=config.webhook_url,
            webhook_type=config.webhook_type,
            webhook_token=(
                config.webhook_token.get_secret_value()
                if config.webhook_token
                else None
            ),
        )
        google_health_repository = GoogleHealthRepository(conn, mutex=db_mutex)
        google_health_auth = None
        google_health_client = None
        if config.google_health_is_configured:
            client_id = cast(SecretStr, config.google_health_client_id)
            client_secret = cast(SecretStr, config.google_health_client_secret)
            encryption_key = cast(
                SecretStr,
                config.google_health_token_encryption_key,
            )
            redirect_uri = cast(str, config.google_health_redirect_uri)
            token_cipher = TokenCipher(encryption_key.get_secret_value())
            google_health_auth = GoogleHealthAuth(
                client_id=client_id.get_secret_value(),
                client_secret=client_secret.get_secret_value(),
                redirect_uri=redirect_uri,
                repository=google_health_repository,
                token_cipher=token_cipher,
            )
            google_health_client = GoogleHealthAPIClient(
                google_health_repository,
                token_cipher,
                client_id=client_id.get_secret_value(),
                client_secret=client_secret.get_secret_value(),
                timezone=ZoneInfo(config.timezone),
            )
        service = cls(
            config=config,
            workflow_repository=workflow_repository,
            schedule_state_repository=schedule_state_repository,
            run_repository=run_repository,
            step_run_repository=step_run_repository,
            lock_manager=lock_manager,
            scheduler=ScheduleTriggerApp(
                workflow_repository=workflow_repository,
                schedule_state_repository=schedule_state_repository,
                run_repository=run_repository,
                workflows=workflows,
                timezone=config.timezone,
            ),
            dispatcher=RunDispatcher(
                run_repository=run_repository,
                step_run_repository=step_run_repository,
                workflows=workflows,
                lock_manager=lock_manager,
                subprocess_executor=SubprocessStepExecutor(log_store),
                inprocess_executor=InProcessStepExecutor(log_store),
                notification_service=notification_service,
                poll_seconds=config.dispatcher_poll_seconds,
                heartbeat_seconds=config.lock_heartbeat_seconds,
                max_concurrent_runs=config.max_concurrent_runs,
            ),
            log_store=log_store,
            google_health_repository=google_health_repository,
            google_health_auth=google_health_auth,
            google_health_client=google_health_client,
        )
        service.workflow_repository.register_workflows(workflows)
        return service

    def start(self) -> None:
        """scheduler/dispatcher を起動し、再起動後の残状態を収束させる。"""
        self.run_repository.mark_stale_running_runs_failed()
        self.lock_manager.cleanup_stale_locks()
        self.scheduler.start()
        self.dispatcher.start()

    def stop(self) -> None:
        """scheduler/dispatcher を停止する。"""
        self.dispatcher.stop()
        self.scheduler.shutdown()

    def list_workflows(self) -> list[dict]:
        """workflow 一覧を返す。"""
        return self.workflow_repository.list_workflows()

    def get_workflow(self, workflow_id: str) -> dict:
        """workflow 詳細を返す。"""
        return self.workflow_repository.get_workflow(workflow_id)

    def list_runs(self, workflow_id: str | None = None) -> list[WorkflowRun]:
        """run 一覧を返す。"""
        return self.run_repository.list_runs(workflow_id=workflow_id)

    def get_run_detail(self, run_id: str) -> dict:
        """run 詳細と step 一覧を返す。"""
        run = self.run_repository.get_run(run_id)
        steps = self.step_run_repository.list_step_runs(run_id)
        duration_seconds = (
            (run.finished_at - run.started_at).total_seconds()
            if run.started_at is not None and run.finished_at is not None
            else None
        )
        return {
            "run": run,
            "steps": steps,
            "duration_seconds": duration_seconds,
        }

    def trigger_workflow(
        self,
        workflow_id: str,
        *,
        requested_by: str = "api",
    ) -> WorkflowRun:
        """手動 run を queue に積む。"""
        return self.run_repository.enqueue_run(
            workflow_id=workflow_id,
            trigger_type=TriggerType.MANUAL,
            queued_reason=QueuedReason.MANUAL_REQUEST,
            requested_by=requested_by,
        )

    def trigger_google_health_ingest(
        self,
        request: dict,
        *,
        requested_by: str = "api",
    ) -> WorkflowRun:
        """Google Health取り込みrunを入力付きでqueueへ積む。"""
        return self.run_repository.enqueue_run(
            workflow_id="google_health_ingest_workflow",
            trigger_type=TriggerType.MANUAL,
            queued_reason=QueuedReason.MANUAL_REQUEST,
            requested_by=requested_by,
            result_summary={"request": request},
        )

    def set_workflow_enabled(self, workflow_id: str, enabled: bool) -> dict:
        """workflow の有効/無効フラグを更新し scheduler を再同期する。"""
        workflow = self.workflow_repository.set_workflow_enabled(workflow_id, enabled)
        self.scheduler.sync_jobs()
        return workflow

    def retry_run(self, run_id: str, *, requested_by: str = "api") -> WorkflowRun:
        """失敗 run の再実行 run を queue に積む。"""
        source_run = self.run_repository.get_run(run_id)
        return self.run_repository.enqueue_run(
            workflow_id=source_run.workflow_id,
            trigger_type=TriggerType.RETRY,
            queued_reason=QueuedReason.RETRY_REQUEST,
            requested_by=requested_by,
            parent_run_id=source_run.run_id,
            result_summary=source_run.result_summary,
        )

    def cancel_run(self, run_id: str) -> WorkflowRun:
        """queued run を cancel する。"""
        return self.run_repository.cancel_run(run_id)

    def get_step_log(self, run_id: str, step_id: str) -> str:
        """指定 step の最新 attempt log を返す。"""
        steps = [
            step
            for step in self.step_run_repository.list_step_runs(run_id)
            if step.step_id == step_id and step.log_path
        ]
        if not steps:
            raise WorkflowNotFoundError(f"step log not found: {run_id}/{step_id}")
        return self.log_store.read_log(steps[-1].log_path or "")

    def enqueue_browser_history_compact(
        self,
        targets: list[tuple[int, int]],
        *,
        sync_id: str | None = None,
        target_months: list[tuple[int, int]] | None = None,
        requested_by: str = "api",
    ) -> WorkflowRun:
        """Browser History ingest 後の即時 compact run を積む。

        sync_id / target_months を渡すと
        compact 完了後に YouTube ingest を enqueue する。
        """
        result_summary: dict = {
            "compaction_targets": [
                {"year": year, "month": month} for year, month in targets
            ]
        }
        if sync_id and target_months:
            result_summary["youtube_ingest"] = {
                "sync_id": sync_id,
                "target_months": [
                    {"year": year, "month": month} for year, month in target_months
                ],
            }
        return self.scheduler.enqueue_event_run(
            workflow_id="browser_history_compact_workflow",
            requested_by=requested_by,
            result_summary=result_summary,
        )
