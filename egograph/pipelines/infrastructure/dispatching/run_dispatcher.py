"""Queued workflow run dispatching."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from pipelines.domain.errors import AuthenticationError, WorkflowLockUnavailableError
from pipelines.domain.notification import NotificationData, NotificationEvent
from pipelines.domain.workflow import (
    StepDefinition,
    StepExecutorType,
    StepRunStatus,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.infrastructure.db.run_repository import RunRepository
from pipelines.infrastructure.db.step_run_repository import StepRunRepository
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
from pipelines.infrastructure.notification.service import NotificationService

logger = logging.getLogger(__name__)

NOTIFICATION_SOURCE = "urn:egograph:pipelines"
NOTIFICATION_TYPE = "egograph.pipelines.workflow_failed"


class _DispatchOutcome:
    """1回の dispatch 試行結果。"""

    def __init__(self, *, dispatched: bool, blocked_run_id: str | None = None) -> None:
        self.dispatched = dispatched
        self.blocked_run_id = blocked_run_id


class RunDispatcher:
    """queued run を拾い、workflow step を順序実行する。"""

    def __init__(
        self,
        *,
        run_repository: RunRepository,
        step_run_repository: StepRunRepository,
        workflows: dict[str, WorkflowDefinition],
        lock_manager: WorkflowLockManager,
        subprocess_executor: SubprocessStepExecutor,
        inprocess_executor: InProcessStepExecutor,
        notification_service: NotificationService,
        poll_seconds: float,
        heartbeat_seconds: int,
        max_concurrent_runs: int = 1,
    ) -> None:
        self._run_repository = run_repository
        self._step_run_repository = step_run_repository
        self._workflows = workflows
        self._lock_manager = lock_manager
        self._subprocess_executor = subprocess_executor
        self._inprocess_executor = inprocess_executor
        self._notification_service = notification_service
        self._poll_seconds = poll_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._max_concurrent_runs = max(1, max_concurrent_runs)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker_mutex = threading.Lock()
        self._worker_threads: dict[str, threading.Thread] = {}

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
        for worker in self._take_worker_snapshot():
            worker.join(timeout=max(1.0, self._heartbeat_seconds))

    def run_forever(self) -> None:
        """停止要求が来るまで dispatch を続ける。"""
        while not self._stop_event.is_set():
            try:
                dispatched = self._dispatch_available_runs()
            except Exception:
                logger.exception("dispatcher loop crashed unexpectedly")
                dispatched = False
            if not dispatched:
                self._stop_event.wait(self._poll_seconds)

    def _dispatch_available_runs(self) -> bool:
        dispatched = False
        blocked_run_ids: set[str] = set()
        while not self._stop_event.is_set():
            available_slots = self._available_slots()
            if available_slots <= 0:
                return dispatched
            outcome = self._dispatch_once_in_background(
                excluded_run_ids=blocked_run_ids
            )
            if outcome.blocked_run_id is not None:
                blocked_run_ids.add(outcome.blocked_run_id)
                continue
            blocked_run_ids.clear()
            if not outcome.dispatched:
                return dispatched
            dispatched = True
        return dispatched

    def dispatch_once(self) -> bool:
        """queued run を1件処理する。"""
        run: WorkflowRun | None = None
        workflow: WorkflowDefinition | None = None
        try:
            run = self._run_repository.lease_next_queued_run()
            if run is None:
                return False

            workflow = self._workflows.get(run.workflow_id)
            if workflow is None:
                self._fail_unknown_workflow_run(run)
                return True

            try:
                lease = self._lock_manager.acquire(
                    lock_key=workflow.lock_key,
                    run_id=run.run_id,
                )
            except WorkflowLockUnavailableError as exc:
                self._run_repository.requeue_run(
                    run_id=run.run_id,
                    reason=str(exc),
                )
                return False

            self._execute_run_with_heartbeat(workflow, run, lease)
            return True
        except Exception as exc:
            if run is None:
                logger.exception("dispatch_once failed before leasing a run")
                return False
            logger.exception(
                "dispatch_once failed unexpectedly for run_id=%s",
                run.run_id,
            )
            self._mark_run_failed_after_unexpected_exception(
                run=run,
                workflow=workflow,
                exc=exc,
            )
            return True

    def _dispatch_once_in_background(
        self,
        *,
        excluded_run_ids: set[str],
    ) -> _DispatchOutcome:
        run: WorkflowRun | None = None
        workflow: WorkflowDefinition | None = None
        try:
            run = self._run_repository.lease_next_queued_run(
                excluded_run_ids=excluded_run_ids
            )
            if run is None:
                return _DispatchOutcome(dispatched=False)

            workflow = self._workflows.get(run.workflow_id)
            if workflow is None:
                self._fail_unknown_workflow_run(run)
                return _DispatchOutcome(dispatched=True)

            try:
                lease = self._lock_manager.acquire(
                    lock_key=workflow.lock_key,
                    run_id=run.run_id,
                )
            except WorkflowLockUnavailableError as exc:
                self._run_repository.requeue_run(
                    run_id=run.run_id,
                    reason=str(exc),
                )
                return _DispatchOutcome(
                    dispatched=False,
                    blocked_run_id=run.run_id,
                )

            worker = threading.Thread(
                target=self._execute_run_in_worker,
                args=(workflow, run, lease),
                daemon=True,
                name=f"workflow-run-{run.run_id}",
            )
            with self._worker_mutex:
                self._worker_threads[run.run_id] = worker
            worker.start()
            return _DispatchOutcome(dispatched=True)
        except Exception as exc:
            if run is None:
                logger.exception("dispatch_once failed before leasing a run")
                return _DispatchOutcome(dispatched=False)
            logger.exception(
                "dispatch_once failed unexpectedly for run_id=%s",
                run.run_id,
            )
            self._mark_run_failed_after_unexpected_exception(
                run=run,
                workflow=workflow,
                exc=exc,
            )
            return _DispatchOutcome(dispatched=True)

    def _heartbeat_loop(
        self,
        lease: WorkflowLease,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.wait(self._heartbeat_seconds):
            try:
                # Heartbeat failure should not kill the background thread silently.
                self._lock_manager.heartbeat(lease)
            except Exception as exc:
                logger.warning(
                    "workflow heartbeat failed: lock_key=%s, run_id=%s, error=%s: %s",
                    lease.lock_key,
                    lease.run_id,
                    type(exc).__name__,
                    exc,
                )

    def _execute_run(
        self,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
    ) -> None:
        last_summary: dict | None = None
        try:
            for sequence_no, step in enumerate(workflow.steps, start=1):
                success, last_summary, error_message, last_exc = self._execute_step(
                    workflow=workflow,
                    run=run,
                    step=step,
                    sequence_no=sequence_no,
                )
                if not success:
                    final_error = error_message or f"step failed: {step.step_id}"
                    self._skip_remaining_steps(
                        run=run,
                        steps=workflow.steps[sequence_no:],
                        first_sequence_no=sequence_no + 1,
                    )
                    self._run_repository.update_run_result(
                        run_id=run.run_id,
                        status=WorkflowRunStatus.FAILED,
                        error_message=final_error,
                        result_summary=last_summary,
                    )
                    self._notify_failure(
                        workflow=workflow,
                        run=run,
                        error_message=final_error,
                        exc=last_exc,
                    )
                    return
            final_status = _status_from_summary(last_summary)
            error_message = (
                _error_from_summary(last_summary)
                if final_status
                in {
                    WorkflowRunStatus.PARTIAL_FAILED,
                    WorkflowRunStatus.FAILED,
                }
                else None
            )
            self._run_repository.update_run_result(
                run_id=run.run_id,
                status=final_status,
                error_message=error_message,
                result_summary=last_summary,
            )
            if final_status == WorkflowRunStatus.FAILED:
                self._notify_failure(
                    workflow=workflow,
                    run=run,
                    error_message=error_message or "workflow reported failed status",
                    exc=None,
                )
        except Exception as exc:
            logger.exception(
                "run execution crashed unexpectedly: run_id=%s",
                run.run_id,
            )
            self._mark_run_failed_after_unexpected_exception(
                workflow=workflow,
                run=run,
                exc=exc,
            )

    def _execute_step(
        self,
        *,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
        step: StepDefinition,
        sequence_no: int,
    ) -> tuple[bool, dict | None, str | None, Exception | None]:
        """step を retry 込みで実行する。

        戻り値 ``exception`` は失敗時のみ設定され、通知の ``custom_message``
        組み立てのために ``_execute_run`` まで持ち越される。
        """
        last_error_message: str | None = None
        last_exception: Exception | None = None
        for attempt_no in range(1, step.max_attempts + 1):
            step_run = self._step_run_repository.insert_step_run(
                run_id=run.run_id,
                step_id=step.step_id,
                step_name=step.step_name,
                sequence_no=sequence_no,
                attempt_no=attempt_no,
                command=self._format_command(step),
            )
            self._step_run_repository.set_step_running(step_run.step_run_id)
            try:
                result = self._execute_definition(
                    workflow_id=workflow.workflow_id,
                    run=run,
                    step=step,
                    attempt_no=attempt_no,
                )
            except Exception as exc:
                # Treat an unexpected executor crash as a failed attempt so the
                # run can still reach a terminal state through the normal path.
                self._record_unexpected_step_exception(
                    step_run_id=step_run.step_run_id,
                    exc=exc,
                )
                last_error_message = f"{type(exc).__name__}: {exc}"
                last_exception = exc
                if isinstance(exc, AuthenticationError):
                    return False, None, last_error_message, exc
                if attempt_no < step.max_attempts and step.retry_delay_seconds > 0:
                    time.sleep(step.retry_delay_seconds)
                continue
            self._step_run_repository.update_step_result(
                step_run_id=step_run.step_run_id,
                status=result.status,
                exit_code=result.exit_code,
                stdout_tail=result.stdout_tail,
                stderr_tail=result.stderr_tail,
                log_path=result.log_path,
                result_summary=result.result_summary,
            )
            if result.status == StepRunStatus.SUCCEEDED:
                return True, result.result_summary, None, None
            last_error_message = result.error_message
            if attempt_no < step.max_attempts and step.retry_delay_seconds > 0:
                time.sleep(step.retry_delay_seconds)
        return False, None, last_error_message, last_exception

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
            step_run = self._step_run_repository.insert_step_run(
                run_id=run.run_id,
                step_id=step.step_id,
                step_name=step.step_name,
                sequence_no=first_sequence_no + offset,
                attempt_no=1,
                command=self._format_command(step),
                status=StepRunStatus.SKIPPED,
            )
            self._step_run_repository.update_step_result(
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

    def _execute_run_with_heartbeat(
        self,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
        lease: WorkflowLease,
    ) -> None:
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
            try:
                self._lock_manager.release(lease)
            except Exception:
                logger.exception(
                    "failed to release workflow lease: lock_key=%s, run_id=%s",
                    lease.lock_key,
                    lease.run_id,
                )

    def _execute_run_in_worker(
        self,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
        lease: WorkflowLease,
    ) -> None:
        try:
            self._execute_run_with_heartbeat(workflow, run, lease)
        finally:
            with self._worker_mutex:
                self._worker_threads.pop(run.run_id, None)

    def _available_slots(self) -> int:
        with self._worker_mutex:
            finished_run_ids = [
                run_id
                for run_id, worker in self._worker_threads.items()
                if not worker.is_alive()
            ]
            for run_id in finished_run_ids:
                self._worker_threads.pop(run_id, None)
            active_count = len(self._worker_threads)
        return self._max_concurrent_runs - active_count

    def _take_worker_snapshot(self) -> list[threading.Thread]:
        with self._worker_mutex:
            return list(self._worker_threads.values())

    def _fail_unknown_workflow_run(self, run: WorkflowRun) -> None:
        logger.error(
            "unknown workflow: %s, run_id: %s",
            run.workflow_id,
            run.run_id,
        )
        self._run_repository.update_run_result(
            run_id=run.run_id,
            status=WorkflowRunStatus.FAILED,
            error_message=f"unknown workflow: {run.workflow_id}",
        )

    def _record_unexpected_step_exception(
        self,
        *,
        step_run_id: str,
        exc: Exception,
    ) -> None:
        self._step_run_repository.update_step_result(
            step_run_id=step_run_id,
            status=StepRunStatus.FAILED,
            exit_code=None,
            stdout_tail="",
            stderr_tail=f"{type(exc).__name__}: {exc}",
            log_path=None,
            result_summary=None,
        )

    def _mark_run_failed_after_unexpected_exception(
        self,
        *,
        run: WorkflowRun,
        workflow: WorkflowDefinition | None,
        exc: Exception,
    ) -> None:
        """予期しない例外で run を FAILED にし、可能なら通知も送る。"""
        error_message = f"unexpected dispatcher error: {type(exc).__name__}: {exc}"
        try:
            # Persist the failure explicitly so startup reconcile does not need
            # to clean up a RUNNING row after an in-loop crash.
            self._run_repository.update_run_result(
                run_id=run.run_id,
                status=WorkflowRunStatus.FAILED,
                error_message=error_message,
            )
        except Exception:
            logger.exception(
                "failed to persist unexpected dispatcher error for run_id=%s",
                run.run_id,
            )
        if workflow is not None:
            self._notify_failure(
                workflow=workflow,
                run=run,
                error_message=error_message,
                exc=exc,
            )

    def _notify_failure(
        self,
        *,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
        error_message: str,
        exc: Exception | None,
    ) -> None:
        """失敗イベントを構築して NotificationService に委譲する。"""
        event = NotificationEvent(
            source=NOTIFICATION_SOURCE,
            type=NOTIFICATION_TYPE,
            time=datetime.now(UTC),
            data=NotificationData(
                workflow_id=workflow.workflow_id,
                run_id=run.run_id,
                error_message=error_message,
                custom_message=None,
            ),
        )
        self._notification_service.notify(event, exc=exc)


def _status_from_summary(
    summary: dict | None,
) -> WorkflowRunStatus:
    if summary is None:
        return WorkflowRunStatus.SUCCEEDED
    raw_status = summary.get("status", WorkflowRunStatus.SUCCEEDED.value)
    normalized_status = str(raw_status).strip().lower()
    terminal_statuses = {
        status.value: status
        for status in (
            WorkflowRunStatus.SUCCEEDED,
            WorkflowRunStatus.PARTIAL_FAILED,
            WorkflowRunStatus.FAILED,
        )
    }
    status = terminal_statuses.get(normalized_status)
    if status is not None:
        return status
    logger.warning(
        "workflow returned non-terminal or unknown summary status: status=%r",
        raw_status,
    )
    return WorkflowRunStatus.SUCCEEDED


def _error_from_summary(summary: dict | None) -> str:
    if summary is None:
        return "workflow reported failed status"
    errors = summary.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(error) for error in errors)
    return "workflow reported failed status"
