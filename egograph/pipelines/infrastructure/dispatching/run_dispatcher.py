"""Queued workflow run dispatching."""

from __future__ import annotations

import logging
import threading
import time

from pipelines.domain.errors import WorkflowLockUnavailableError
from pipelines.domain.workflow import (
    StepDefinition,
    StepExecutorType,
    StepRunStatus,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.infrastructure.db.repositories import WorkflowStateRepository
from pipelines.infrastructure.dispatching.lock_manager import (
    WorkflowLease,
    WorkflowLockManager,
)
from pipelines.infrastructure.execution.inprocess_executor import (
    InProcessStepExecutor,
)
from pipelines.infrastructure.execution.subprocess_executor import (
    SubprocessStepExecutor,
)

logger = logging.getLogger(__name__)


class RunDispatcher:
    """queued run を拾い、workflow step を順序実行する。"""

    def __init__(
        self,
        *,
        repository: WorkflowStateRepository,
        workflows: dict[str, WorkflowDefinition],
        lock_manager: WorkflowLockManager,
        subprocess_executor: SubprocessStepExecutor,
        inprocess_executor: InProcessStepExecutor,
        poll_seconds: float,
        heartbeat_seconds: int,
    ) -> None:
        self._repository = repository
        self._workflows = workflows
        self._lock_manager = lock_manager
        self._subprocess_executor = subprocess_executor
        self._inprocess_executor = inprocess_executor
        self._poll_seconds = poll_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """background dispatcher を開始する。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """background dispatcher を停止する。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self._poll_seconds * 2))

    def run_forever(self) -> None:
        """停止要求が来るまで dispatch を続ける。"""
        while not self._stop_event.is_set():
            dispatched = self.dispatch_once()
            if not dispatched:
                self._stop_event.wait(self._poll_seconds)

    def dispatch_once(self) -> bool:
        """queued run を1件処理する。"""
        run = self._repository.lease_next_queued_run()
        if run is None:
            return False

        workflow = self._workflows.get(run.workflow_id)
        if workflow is None:
            self._repository.update_run_result(
                run_id=run.run_id,
                status=WorkflowRunStatus.FAILED,
                error_message=f"unknown workflow: {run.workflow_id}",
            )
            return True

        try:
            lease = self._lock_manager.acquire(
                lock_key=workflow.lock_key,
                run_id=run.run_id,
            )
        except WorkflowLockUnavailableError as exc:
            self._repository.update_run_result(
                run_id=run.run_id,
                status=WorkflowRunStatus.FAILED,
                error_message=str(exc),
            )
            return True

        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(lease, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            self._execute_run(workflow, run)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=max(1, self._heartbeat_seconds))
            self._lock_manager.release(lease)
        return True

    def _heartbeat_loop(
        self,
        lease: WorkflowLease,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.wait(self._heartbeat_seconds):
            self._lock_manager.heartbeat(lease)

    def _execute_run(
        self,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
    ) -> None:
        last_summary: dict | None = None
        for sequence_no, step in enumerate(workflow.steps, start=1):
            success, last_summary = self._execute_step(
                workflow=workflow,
                run=run,
                step=step,
                sequence_no=sequence_no,
            )
            if not success:
                self._skip_remaining_steps(
                    run=run,
                    steps=workflow.steps[sequence_no:],
                    first_sequence_no=sequence_no + 1,
                )
                self._repository.update_run_result(
                    run_id=run.run_id,
                    status=WorkflowRunStatus.FAILED,
                    error_message=f"step failed: {step.step_id}",
                    result_summary=last_summary,
                )
                return
        self._repository.update_run_result(
            run_id=run.run_id,
            status=WorkflowRunStatus.SUCCEEDED,
            result_summary=last_summary,
        )

    def _execute_step(
        self,
        *,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
        step: StepDefinition,
        sequence_no: int,
    ) -> tuple[bool, dict | None]:
        for attempt_no in range(1, step.max_attempts + 1):
            step_run = self._repository.insert_step_run(
                run_id=run.run_id,
                step_id=step.step_id,
                step_name=step.step_name,
                sequence_no=sequence_no,
                attempt_no=attempt_no,
                command=self._format_command(step),
            )
            self._repository.set_step_running(step_run.step_run_id)
            result = self._execute_definition(
                workflow_id=workflow.workflow_id,
                run=run,
                step=step,
                attempt_no=attempt_no,
            )
            self._repository.update_step_result(
                step_run_id=step_run.step_run_id,
                status=result.status,
                exit_code=result.exit_code,
                stdout_tail=result.stdout_tail,
                stderr_tail=result.stderr_tail,
                log_path=result.log_path,
                result_summary=result.result_summary,
            )
            if result.status == StepRunStatus.SUCCEEDED:
                return True, result.result_summary
            if attempt_no < step.max_attempts and step.retry_delay_seconds > 0:
                time.sleep(step.retry_delay_seconds)
        return False, None

    def _execute_definition(
        self,
        *,
        workflow_id: str,
        run: WorkflowRun,
        step: StepDefinition,
        attempt_no: int,
    ):
        if step.executor_type == StepExecutorType.SUBPROCESS:
            return self._subprocess_executor.execute(
                workflow_id=workflow_id,
                run=run,
                step=step,
                attempt_no=attempt_no,
            )
        return self._inprocess_executor.execute(
            workflow_id=workflow_id,
            run=run,
            step=step,
            attempt_no=attempt_no,
        )

    def _skip_remaining_steps(
        self,
        *,
        run: WorkflowRun,
        steps: tuple[StepDefinition, ...],
        first_sequence_no: int,
    ) -> None:
        for offset, step in enumerate(steps):
            step_run = self._repository.insert_step_run(
                run_id=run.run_id,
                step_id=step.step_id,
                step_name=step.step_name,
                sequence_no=first_sequence_no + offset,
                attempt_no=1,
                command=self._format_command(step),
                status=StepRunStatus.SKIPPED,
            )
            self._repository.update_step_result(
                step_run_id=step_run.step_run_id,
                status=StepRunStatus.SKIPPED,
                exit_code=None,
                stdout_tail="",
                stderr_tail="",
                log_path=None,
                result_summary=None,
            )

    @staticmethod
    def _format_command(step: StepDefinition) -> str:
        if step.executor_type == StepExecutorType.SUBPROCESS:
            return " ".join(step.command)
        return step.callable_ref or ""
