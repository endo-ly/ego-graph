import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from pipelines.domain.errors import AuthenticationError
from pipelines.domain.workflow import (
    QueuedReason,
    StepDefinition,
    StepExecutionResult,
    StepExecutorType,
    StepRunStatus,
    TriggerType,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.run_repository import RunRepository
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.infrastructure.db.step_run_repository import StepRunRepository
from pipelines.infrastructure.db.workflow_repository import WorkflowRepository
from pipelines.infrastructure.dispatching.lock_manager import WorkflowLockManager
from pipelines.infrastructure.dispatching.run_dispatcher import (
    RunDispatcher,
    _LeaseState,
    _status_from_summary,
)
from pipelines.infrastructure.execution.inprocess_executor import InProcessStepExecutor
from pipelines.infrastructure.execution.log_store import LocalLogStore
from pipelines.infrastructure.execution.subprocess_executor import (
    SubprocessStepExecutor,
)
from pipelines.infrastructure.notification.service import NotificationService


def _build_dispatcher(
    tmp_path,
    workflows,
    *,
    max_concurrent_runs=1,
    heartbeat_seconds=60,
    notification_service=None,
):
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    db_mutex = threading.RLock()
    workflow_repository = WorkflowRepository(conn, mutex=db_mutex)
    workflow_repository.register_workflows(workflows)
    run_repository = RunRepository(workflow_repository, conn, mutex=db_mutex)
    step_run_repository = StepRunRepository(conn, mutex=db_mutex)
    log_store = LocalLogStore(tmp_path / "logs")
    lock_manager = WorkflowLockManager(conn, lease_seconds=60, mutex=db_mutex)
    dispatcher = RunDispatcher(
        run_repository=run_repository,
        step_run_repository=step_run_repository,
        workflows=workflows,
        lock_manager=lock_manager,
        subprocess_executor=SubprocessStepExecutor(log_store),
        inprocess_executor=InProcessStepExecutor(log_store),
        notification_service=notification_service
        or NotificationService(webhook_url=None),
        poll_seconds=0.01,
        heartbeat_seconds=heartbeat_seconds,
        max_concurrent_runs=max_concurrent_runs,
    )
    return run_repository, step_run_repository, dispatcher, lock_manager


def test_dispatch_once_succeeds_and_writes_step_log(tmp_path):
    """成功 step のログと summary を保存できる。"""
    # Arrange
    workflows = {
        "dummy_workflow": WorkflowDefinition(
            workflow_id="dummy_workflow",
            name="Dummy workflow",
            description="Dummy workflow for tests",
            steps=(
                StepDefinition(
                    step_id="succeed",
                    step_name="Succeed",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    # Act
    dispatched = dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)

    # Assert
    assert dispatched is True
    assert updated_run.status == WorkflowRunStatus.SUCCEEDED
    assert updated_run.result_summary == {"message": "ok"}
    assert len(steps) == 1
    assert steps[0].stdout_tail == "dummy step succeeded\n"
    assert steps[0].log_path is not None
    assert "dummy step succeeded" in LocalLogStore.read_log(steps[0].log_path)


def test_dispatch_once_persists_partial_failed_summary_status(tmp_path):
    """step summaryのpartial_failedをrun statusへ反映する。"""
    # Arrange
    workflows = {
        "partial_workflow": WorkflowDefinition(
            workflow_id="partial_workflow",
            name="Partial workflow",
            description="Partial workflow for tests",
            steps=(
                StepDefinition(
                    step_id="partial",
                    step_name="Partial",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref=(
                        "pipelines.tests.support.dummy_steps:partial_failure"
                    ),
                ),
            ),
        )
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(tmp_path, workflows)
    run = run_repository.enqueue_run(
        workflow_id="partial_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    # Act
    dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)

    # Assert
    assert updated_run.status is WorkflowRunStatus.PARTIAL_FAILED
    assert updated_run.last_error_message == "sleep: unavailable"
    assert updated_run.result_summary == {
        "status": "partial_failed",
        "errors": ["sleep: unavailable"],
    }


@pytest.mark.parametrize("summary_status", ["unexpected", "running", "queued"])
def test_invalid_summary_status_logs_warning_and_succeeds(caplog, summary_status):
    """未知または非終端statusは警告を残してsucceededへ寄せる。"""
    with caplog.at_level(logging.WARNING):
        status = _status_from_summary({"status": summary_status})

    assert status is WorkflowRunStatus.SUCCEEDED
    assert "non-terminal or unknown summary status" in caplog.text


def test_dispatch_once_skips_remaining_steps_after_failure(tmp_path):
    """前段 step 失敗時は後続 step を skipped にする。"""
    # Arrange
    workflows = {
        "dummy_workflow": WorkflowDefinition(
            workflow_id="dummy_workflow",
            name="Dummy workflow",
            description="Dummy workflow for tests",
            steps=(
                StepDefinition(
                    step_id="fail",
                    step_name="Fail",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:fail",
                ),
                StepDefinition(
                    step_id="succeed",
                    step_name="Succeed",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    # Act
    dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)

    # Assert
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert [step.status.value for step in steps] == ["failed", "skipped"]
    assert "RuntimeError: boom" in (steps[0].stderr_tail or "")


def test_dispatch_once_executes_step_with_run_summary_context(tmp_path):
    """event run の result_summary を in-process step へ渡せる。"""
    # Arrange
    workflows = {
        "event_workflow": WorkflowDefinition(
            workflow_id="event_workflow",
            name="Event workflow",
            description="Event workflow",
            steps=(
                StepDefinition(
                    step_id="echo",
                    step_name="Echo",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:echo_run_summary",
                ),
            ),
        )
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(tmp_path, workflows)
    run = run_repository.enqueue_run(
        workflow_id="event_workflow",
        trigger_type=TriggerType.EVENT,
        queued_reason=QueuedReason.EVENT_ENQUEUE,
        result_summary={"compaction_targets": [{"year": 2026, "month": 4}]},
    )

    # Act
    dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)

    # Assert
    assert updated_run.status == WorkflowRunStatus.SUCCEEDED
    assert updated_run.result_summary == {
        "compaction_targets": [{"year": 2026, "month": 4}]
    }


def test_dispatch_once_requeues_run_when_lock_is_active(tmp_path):
    """同一 workflow lock が active なら run を failed にせず queued に戻す。"""
    # Arrange
    workflows = {
        "dummy_workflow": WorkflowDefinition(
            workflow_id="dummy_workflow",
            name="Dummy workflow",
            description="Dummy workflow for tests",
            concurrency_key="shared-lock",
            steps=(
                StepDefinition(
                    step_id="succeed",
                    step_name="Succeed",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, lock_manager = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    lock_manager.acquire(lock_key="shared-lock", run_id="other-run")

    # Act
    dispatched = dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)

    # Assert
    assert dispatched is False
    assert updated_run.status == WorkflowRunStatus.QUEUED
    assert updated_run.started_at is None
    assert updated_run.last_error_message == "workflow lock is active: shared-lock"
    assert steps == []


def test_dispatch_once_marks_inprocess_step_failed_on_timeout(tmp_path):
    """in-process callable でも step.timeout_seconds を超えたら failed にする。"""
    # Arrange
    workflows = {
        "timeout_workflow": WorkflowDefinition(
            workflow_id="timeout_workflow",
            name="Timeout workflow",
            description="Timeout workflow for tests",
            steps=(
                StepDefinition(
                    step_id="sleep",
                    step_name="Sleep",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:sleep_too_long",
                    timeout_seconds=1,
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="timeout_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    # Act
    dispatched = dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)

    # Assert
    assert dispatched is True
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert updated_run.last_error_message == "step timed out after 1s"
    assert len(steps) == 1
    assert steps[0].status == StepRunStatus.FAILED
    assert steps[0].exit_code is None
    assert "TimeoutError: step timed out after 1s" in (steps[0].stderr_tail or "")


def test_dispatch_once_logs_unknown_workflow_and_marks_run_failed(tmp_path, caplog):
    """未知 workflow はエラーログ付きで failed にする。"""
    workflows = {
        "dummy_workflow": WorkflowDefinition(
            workflow_id="dummy_workflow",
            name="Dummy workflow",
            description="Dummy workflow for tests",
            steps=(
                StepDefinition(
                    step_id="succeed",
                    step_name="Succeed",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(tmp_path, workflows)
    run = run_repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    dispatcher._workflows = {}

    with caplog.at_level(logging.ERROR):
        dispatched = dispatcher.dispatch_once()

    updated_run = run_repository.get_run(run.run_id)

    assert dispatched is True
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert updated_run.last_error_message == "unknown workflow: dummy_workflow"
    assert "unknown workflow: dummy_workflow" in caplog.text
    assert run.run_id in caplog.text


def test_dispatch_once_marks_step_and_run_failed_on_unexpected_executor_error(tmp_path):
    """executor が予期せず例外を投げても step/run を failed にする。"""
    workflows = {
        "dummy_workflow": WorkflowDefinition(
            workflow_id="dummy_workflow",
            name="Dummy workflow",
            description="Dummy workflow for tests",
            steps=(
                StepDefinition(
                    step_id="explode",
                    step_name="Explode",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
                StepDefinition(
                    step_id="never",
                    step_name="Never",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    def _raise(**_kwargs):
        raise RuntimeError("boom")

    dispatcher._inprocess_executor.execute = _raise

    dispatched = dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)

    assert dispatched is True
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert updated_run.last_error_message == "RuntimeError: boom"
    assert [step.status for step in steps] == [
        StepRunStatus.FAILED,
        StepRunStatus.SKIPPED,
    ]
    assert steps[0].stderr_tail == "RuntimeError: boom"
    assert steps[0].exit_code is None


def test_dispatch_once_skips_retries_on_authentication_error(tmp_path):
    """AuthenticationError は max_attempts=3 でも1回で即失敗する。"""
    # Arrange
    workflows = {
        "auth_workflow": WorkflowDefinition(
            workflow_id="auth_workflow",
            name="Auth workflow",
            description="Workflow that raises AuthenticationError",
            steps=(
                StepDefinition(
                    step_id="auth_step",
                    step_name="Auth step",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                    max_attempts=3,
                    retry_delay_seconds=0,
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="auth_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    def _raise_auth(**_kwargs):
        raise AuthenticationError("Spotify refresh token revoked")

    dispatcher._inprocess_executor.execute = _raise_auth

    # Act
    dispatched = dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)

    # Assert
    assert dispatched is True
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert "AuthenticationError" in (updated_run.last_error_message or "")
    assert "Spotify refresh token revoked" in (updated_run.last_error_message or "")
    # 1 attempt のみで終了すること（max_attempts=3 だがリトライしない）
    assert len(steps) == 1
    assert steps[0].status == StepRunStatus.FAILED
    assert "AuthenticationError" in (steps[0].stderr_tail or "")


def test_dispatch_once_retries_normal_exception_up_to_max_attempts(tmp_path):
    """通常の例外は max_attempts 回まで retry される（regression）。"""
    # Arrange
    workflows = {
        "retry_workflow": WorkflowDefinition(
            workflow_id="retry_workflow",
            name="Retry workflow",
            description="Workflow that raises RuntimeError",
            steps=(
                StepDefinition(
                    step_id="flaky",
                    step_name="Flaky",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                    max_attempts=3,
                    retry_delay_seconds=0,
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="retry_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    def _raise(**_kwargs):
        raise RuntimeError("transient")

    dispatcher._inprocess_executor.execute = _raise

    # Act
    dispatcher.dispatch_once()
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)

    # Assert: max_attempts=3 すべて試す
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert len(steps) == 3
    assert all(step.status == StepRunStatus.FAILED for step in steps)


def test_dispatch_once_notifies_on_step_failure(tmp_path):
    """step 失敗パスで NotificationService.notify が呼ばれる。"""
    # Arrange
    workflows = {
        "fail_workflow": WorkflowDefinition(
            workflow_id="fail_workflow",
            name="Fail workflow",
            description="Workflow that fails",
            steps=(
                StepDefinition(
                    step_id="boom",
                    step_name="Boom",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    notification_service = NotificationService(webhook_url="https://example.com/hook")
    run_repository, _, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        notification_service=notification_service,
    )
    run = run_repository.enqueue_run(
        workflow_id="fail_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    def _raise(**_kwargs):
        raise RuntimeError("step boom")

    dispatcher._inprocess_executor.execute = _raise

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        dispatcher.dispatch_once()

    # Assert
    updated_run = run_repository.get_run(run.run_id)
    assert updated_run.status == WorkflowRunStatus.FAILED
    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["source"] == "urn:egograph:pipelines"
    assert payload["type"] == "egograph.pipelines.workflow_failed"
    assert payload["data"]["workflow_id"] == "fail_workflow"
    assert payload["data"]["run_id"] == run.run_id
    assert "RuntimeError" in payload["data"]["error_message"]


def test_dispatch_once_notifies_with_custom_message_on_authentication_error(tmp_path):
    """AuthenticationError 起因の失敗で custom_message が payload に乗る。"""
    # Arrange
    workflows = {
        "auth_workflow": WorkflowDefinition(
            workflow_id="auth_workflow",
            name="Auth workflow",
            description="Workflow that raises AuthenticationError",
            steps=(
                StepDefinition(
                    step_id="auth",
                    step_name="Auth",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    notification_service = NotificationService(webhook_url="https://example.com/hook")
    run_repository, _, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        notification_service=notification_service,
    )
    run_repository.enqueue_run(
        workflow_id="auth_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    def _raise(**_kwargs):
        raise AuthenticationError("Spotify refresh token revoked")

    dispatcher._inprocess_executor.execute = _raise

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        dispatcher.dispatch_once()

    # Assert
    payload = mock_post.call_args.kwargs["json"]
    assert payload["data"]["custom_message"] is not None
    assert "spotify_auth.py" in payload["data"]["custom_message"]


def test_dispatch_once_does_not_crash_when_webhook_is_unset(tmp_path):
    """WEBHOOK_URL 未設定で run 失敗しても run は FAILED に遷移する。"""
    # Arrange
    workflows = {
        "fail_workflow": WorkflowDefinition(
            workflow_id="fail_workflow",
            name="Fail workflow",
            description="Workflow that fails",
            steps=(
                StepDefinition(
                    step_id="boom",
                    step_name="Boom",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        notification_service=NotificationService(webhook_url=None),
    )
    run = run_repository.enqueue_run(
        workflow_id="fail_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    def _raise(**_kwargs):
        raise RuntimeError("step boom")

    dispatcher._inprocess_executor.execute = _raise

    # Act
    dispatched = dispatcher.dispatch_once()

    # Assert
    assert dispatched is True
    updated_run = run_repository.get_run(run.run_id)
    assert updated_run.status == WorkflowRunStatus.FAILED


def test_dispatch_once_notifies_on_unexpected_dispatcher_exception(tmp_path):
    """予期しない例外パスでも通知が飛ぶ。"""
    # Arrange
    workflows = {
        "dummy_workflow": WorkflowDefinition(
            workflow_id="dummy_workflow",
            name="Dummy workflow",
            description="dummy",
            steps=(
                StepDefinition(
                    step_id="succeed",
                    step_name="Succeed",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    notification_service = NotificationService(webhook_url="https://example.com/hook")
    run_repository, _, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        notification_service=notification_service,
    )
    run = run_repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    dispatcher._lock_manager.acquire = Mock(side_effect=RuntimeError("lock boom"))

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        dispatcher.dispatch_once()

    # Assert
    updated_run = run_repository.get_run(run.run_id)
    assert updated_run.status == WorkflowRunStatus.FAILED
    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert "unexpected dispatcher error" in payload["data"]["error_message"]


def test_dispatch_once_marks_run_failed_when_lock_manager_crashes(tmp_path, caplog):
    """dispatch_once 想定外例外でも run を failed にして継続可能にする。"""
    workflows = {
        "dummy_workflow": WorkflowDefinition(
            workflow_id="dummy_workflow",
            name="Dummy workflow",
            description="Dummy workflow for tests",
            steps=(
                StepDefinition(
                    step_id="succeed",
                    step_name="Succeed",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(tmp_path, workflows)
    run = run_repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    dispatcher._lock_manager.acquire = Mock(side_effect=RuntimeError("lock boom"))

    with caplog.at_level(logging.ERROR):
        dispatched = dispatcher.dispatch_once()

    updated_run = run_repository.get_run(run.run_id)

    assert dispatched is True
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert (
        updated_run.last_error_message
        == "unexpected dispatcher error: RuntimeError: lock boom"
    )
    assert "dispatch_once failed unexpectedly" in caplog.text


def test_run_forever_keeps_looping_after_dispatch_once_exception(tmp_path, caplog):
    """dispatch_once が一度失敗しても run_forever は次周期へ進む。"""
    _, _, dispatcher, _ = _build_dispatcher(tmp_path, {})
    calls = {"count": 0}

    def _dispatch_available_runs():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("loop boom")
        dispatcher._stop_event.set()
        return False

    dispatcher._dispatch_available_runs = _dispatch_available_runs

    with caplog.at_level(logging.ERROR):
        dispatcher.run_forever()

    assert calls["count"] == 2
    assert "dispatcher loop crashed unexpectedly" in caplog.text


def test_start_runs_distinct_workflows_in_parallel(tmp_path):
    """別 lock_key の run は background dispatcher 上で並列実行される。"""
    workflows = {
        "workflow_a": WorkflowDefinition(
            workflow_id="workflow_a",
            name="Workflow A",
            description="Parallel test workflow A",
            steps=(
                StepDefinition(
                    step_id="sleep",
                    step_name="Sleep",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:sleep_briefly",
                ),
            ),
        ),
        "workflow_b": WorkflowDefinition(
            workflow_id="workflow_b",
            name="Workflow B",
            description="Parallel test workflow B",
            steps=(
                StepDefinition(
                    step_id="sleep",
                    step_name="Sleep",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:sleep_briefly",
                ),
            ),
        ),
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        max_concurrent_runs=2,
    )
    run_a = run_repository.enqueue_run(
        workflow_id="workflow_a",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    run_b = run_repository.enqueue_run(
        workflow_id="workflow_b",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    dispatcher.start()
    try:
        deadline = time.monotonic() + 5
        saw_parallel_running = False
        while time.monotonic() < deadline:
            current_a = run_repository.get_run(run_a.run_id)
            current_b = run_repository.get_run(run_b.run_id)
            if (
                current_a.status == WorkflowRunStatus.RUNNING
                and current_b.status == WorkflowRunStatus.RUNNING
            ):
                saw_parallel_running = True
                break
            if current_a.status in {
                WorkflowRunStatus.SUCCEEDED,
                WorkflowRunStatus.FAILED,
            } and current_b.status in {
                WorkflowRunStatus.SUCCEEDED,
                WorkflowRunStatus.FAILED,
            }:
                break
            time.sleep(0.01)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current_a = run_repository.get_run(run_a.run_id)
            current_b = run_repository.get_run(run_b.run_id)
            if (
                current_a.status == WorkflowRunStatus.SUCCEEDED
                and current_b.status == WorkflowRunStatus.SUCCEEDED
            ):
                break
            time.sleep(0.01)
    finally:
        dispatcher.stop()

    assert saw_parallel_running is True
    assert run_repository.get_run(run_a.run_id).status == WorkflowRunStatus.SUCCEEDED
    assert run_repository.get_run(run_b.run_id).status == WorkflowRunStatus.SUCCEEDED


def test_start_allows_other_workflow_to_progress_while_locked_run_is_requeued(
    tmp_path,
):
    """lock 待ち run が先頭でも、別 workflow を後続で進められる。"""
    workflows = {
        "locked_workflow": WorkflowDefinition(
            workflow_id="locked_workflow",
            name="Locked workflow",
            description="Locked workflow",
            concurrency_key="shared-lock",
            steps=(
                StepDefinition(
                    step_id="sleep",
                    step_name="Sleep",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:sleep_briefly",
                ),
            ),
        ),
        "free_workflow": WorkflowDefinition(
            workflow_id="free_workflow",
            name="Free workflow",
            description="Free workflow",
            steps=(
                StepDefinition(
                    step_id="sleep",
                    step_name="Sleep",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:sleep_briefly",
                ),
            ),
        ),
    }
    run_repository, _, dispatcher, lock_manager = _build_dispatcher(
        tmp_path,
        workflows,
        max_concurrent_runs=2,
    )
    blocked_run = run_repository.enqueue_run(
        workflow_id="locked_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    free_run = run_repository.enqueue_run(
        workflow_id="free_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    held_lease = lock_manager.acquire(lock_key="shared-lock", run_id="other-run")

    dispatcher.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current_free = run_repository.get_run(free_run.run_id)
            if current_free.status == WorkflowRunStatus.SUCCEEDED:
                break
            time.sleep(0.01)
    finally:
        dispatcher.stop()
        lock_manager.release(held_lease)

    blocked_after = run_repository.get_run(blocked_run.run_id)
    free_after = run_repository.get_run(free_run.run_id)

    assert blocked_after.status == WorkflowRunStatus.QUEUED
    assert blocked_after.last_error_message == "workflow lock is active: shared-lock"
    assert free_after.status == WorkflowRunStatus.SUCCEEDED


def test_dispatch_available_runs_skips_blocked_run_within_same_cycle(tmp_path):
    """先頭runがlock待ちでも同じdispatch周期で後続runを進める。"""
    workflows = {
        "locked_workflow": WorkflowDefinition(
            workflow_id="locked_workflow",
            name="Locked workflow",
            description="Locked workflow",
            concurrency_key="shared-lock",
            steps=(
                StepDefinition(
                    step_id="sleep",
                    step_name="Sleep",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:sleep_briefly",
                ),
            ),
        ),
        "free_workflow": WorkflowDefinition(
            workflow_id="free_workflow",
            name="Free workflow",
            description="Free workflow",
            steps=(
                StepDefinition(
                    step_id="sleep",
                    step_name="Sleep",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:sleep_briefly",
                ),
            ),
        ),
    }
    run_repository, _, dispatcher, lock_manager = _build_dispatcher(
        tmp_path,
        workflows,
        max_concurrent_runs=1,
    )
    blocked_run = run_repository.enqueue_run(
        workflow_id="locked_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    free_run = run_repository.enqueue_run(
        workflow_id="free_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    held_lease = lock_manager.acquire(lock_key="shared-lock", run_id="other-run")

    try:
        dispatched = dispatcher._dispatch_available_runs()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            free_status = run_repository.get_run(free_run.run_id).status
            if free_status == WorkflowRunStatus.SUCCEEDED:
                break
            time.sleep(0.01)
    finally:
        dispatcher.stop()
        lock_manager.release(held_lease)

    assert dispatched is True
    assert run_repository.get_run(blocked_run.run_id).status == WorkflowRunStatus.QUEUED
    assert run_repository.get_run(free_run.run_id).status == WorkflowRunStatus.SUCCEEDED


def test_heartbeat_loop_logs_warning_and_stops_after_exception(tmp_path, caplog):
    """heartbeat例外をlease喪失として記録してループを終了する。"""
    _, _, dispatcher, _ = _build_dispatcher(tmp_path, {})
    lease = dispatcher._lock_manager.acquire(lock_key="dummy-lock", run_id="run-1")
    stop_event = Mock()
    stop_event.wait = Mock(side_effect=[False, False, True])
    dispatcher._lock_manager.heartbeat = Mock(
        side_effect=[sqlite3.OperationalError("db busy"), None]
    )

    with caplog.at_level(logging.WARNING):
        dispatcher._heartbeat_loop(lease, stop_event)

    assert dispatcher._lock_manager.heartbeat.call_count == 1
    assert "workflow heartbeat failed" in caplog.text
    assert "db busy" in caplog.text


def test_heartbeat_loop_stops_after_lease_is_lost(tmp_path, caplog):
    """heartbeatがFalseを返したらlease喪失としてループを終了する。"""
    _, _, dispatcher, _ = _build_dispatcher(tmp_path, {})
    lease = dispatcher._lock_manager.acquire(lock_key="dummy-lock", run_id="run-1")
    stop_event = Mock()
    stop_event.wait = Mock(side_effect=[False, False, True])
    dispatcher._lock_manager.heartbeat = Mock(return_value=False)

    with caplog.at_level(logging.WARNING):
        dispatcher._heartbeat_loop(lease, stop_event)

    assert dispatcher._lock_manager.heartbeat.call_count == 1
    assert "workflow lease was lost" in caplog.text


def test_dispatch_once_does_not_start_next_step_after_lease_loss(tmp_path):
    """lease喪失後は後続stepを開始せずrunをFAILEDにする。"""
    workflows = {
        "lease_workflow": WorkflowDefinition(
            workflow_id="lease_workflow",
            name="Lease workflow",
            description="Lease loss test workflow",
            steps=(
                StepDefinition(
                    step_id="first",
                    step_name="First",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
                StepDefinition(
                    step_id="second",
                    step_name="Second",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        heartbeat_seconds=60,
    )
    run = run_repository.enqueue_run(
        workflow_id="lease_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    started_steps: list[str] = []
    heartbeat_available = True

    def execute_step(**kwargs):
        nonlocal heartbeat_available
        started_steps.append(kwargs["step"].step_id)
        if kwargs["step"].step_id == "first":
            heartbeat_available = False
        return StepExecutionResult(
            status=StepRunStatus.SUCCEEDED,
            exit_code=0,
            stdout_tail="",
            stderr_tail="",
            log_path="",
            result_summary=None,
        )

    dispatcher._inprocess_executor.execute = execute_step
    dispatcher._lock_manager.heartbeat = Mock(
        side_effect=lambda _lease: heartbeat_available
    )

    assert dispatcher.dispatch_once() is True

    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)
    assert started_steps == ["first"]
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert "lease_lost:" in (updated_run.last_error_message or "")
    assert [step.status for step in steps] == [
        StepRunStatus.SUCCEEDED,
        StepRunStatus.SKIPPED,
    ]


def test_dispatch_once_does_not_mark_run_succeeded_after_last_step_lease_loss(
    tmp_path,
):
    """最後のstep後にleaseを失ったrunも成功として保存しない。"""
    workflows = {
        "lease_workflow": WorkflowDefinition(
            workflow_id="lease_workflow",
            name="Lease workflow",
            description="Lease loss test workflow",
            steps=(
                StepDefinition(
                    step_id="only",
                    step_name="Only",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        heartbeat_seconds=60,
    )
    run = run_repository.enqueue_run(
        workflow_id="lease_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    lease = dispatcher._lock_manager.acquire(
        lock_key="lease_workflow", run_id=run.run_id
    )
    lease_state = _LeaseState()
    heartbeat_calls = 0

    def heartbeat(_lease):
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        return heartbeat_calls < 3

    dispatcher._lock_manager.heartbeat = heartbeat

    # Act
    dispatcher._execute_run(workflows["lease_workflow"], run, lease_state, lease)
    dispatcher._lock_manager.release(lease)

    # Assert
    updated_run = run_repository.get_run(run.run_id)
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert "lease_lost:" in (updated_run.last_error_message or "")
    assert heartbeat_calls == 3


def test_lease_loss_exception_skips_only_unexecuted_steps_and_preserves_error(
    tmp_path,
):
    """lease喪失後の例外処理が未実行stepと例外理由を保持する。"""
    workflows = {
        "lease_workflow": WorkflowDefinition(
            workflow_id="lease_workflow",
            name="Lease workflow",
            description="Lease loss test workflow",
            steps=(
                StepDefinition(
                    step_id="first",
                    step_name="First",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
                StepDefinition(
                    step_id="second",
                    step_name="Second",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
                StepDefinition(
                    step_id="third",
                    step_name="Third",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, step_run_repository, dispatcher, _ = _build_dispatcher(
        tmp_path, workflows
    )
    run = run_repository.enqueue_run(
        workflow_id="lease_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    lease = dispatcher._lock_manager.acquire(
        lock_key="lease_workflow", run_id=run.run_id
    )
    lease_state = _LeaseState()

    def execute_step(*, step, **_kwargs):
        if step.step_id == "first":
            return True, {"message": "first completed"}, None, None
        lease_state.mark_lost(error_message="lease_lost: heartbeat unavailable")
        raise RuntimeError("step persistence failed")

    dispatcher._execute_step = execute_step

    # Act
    dispatcher._execute_run(workflows["lease_workflow"], run, lease_state, lease)

    # Assert
    updated_run = run_repository.get_run(run.run_id)
    steps = step_run_repository.list_step_runs(run.run_id)
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert updated_run.result_summary == {"message": "first completed"}
    assert "lease_lost: heartbeat unavailable" in (updated_run.last_error_message or "")
    assert "RuntimeError: step persistence failed" in (
        updated_run.last_error_message or ""
    )
    assert [step.sequence_no for step in steps] == [3]
    assert [step.status for step in steps] == [StepRunStatus.SKIPPED]


def test_lease_loss_takes_precedence_over_step_failure(tmp_path):
    """heartbeat失敗とstep失敗が重なった場合はlease喪失を記録する。"""
    workflows = {
        "lease_workflow": WorkflowDefinition(
            workflow_id="lease_workflow",
            name="Lease workflow",
            description="Lease loss test workflow",
            steps=(
                StepDefinition(
                    step_id="only",
                    step_name="Only",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
        )
    }
    run_repository, _, dispatcher, _ = _build_dispatcher(
        tmp_path,
        workflows,
        heartbeat_seconds=60,
    )
    run = run_repository.enqueue_run(
        workflow_id="lease_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )
    heartbeat_available = True

    def execute_step(**_kwargs):
        nonlocal heartbeat_available
        heartbeat_available = False
        return StepExecutionResult(
            status=StepRunStatus.FAILED,
            exit_code=1,
            stdout_tail="",
            stderr_tail="step failed",
            log_path="",
            result_summary=None,
            error_message="step failed",
        )

    dispatcher._inprocess_executor.execute = execute_step

    def heartbeat(_lease):
        if heartbeat_available:
            return True
        raise sqlite3.OperationalError("db busy")

    dispatcher._lock_manager.heartbeat = heartbeat

    dispatcher.dispatch_once()

    updated_run = run_repository.get_run(run.run_id)
    assert updated_run.status == WorkflowRunStatus.FAILED
    assert (updated_run.last_error_message or "").startswith("lease_lost:")


def test_invoke_does_not_pass_workflow_run_to_non_workflow_run_params():
    """第一引数が WorkflowRun 型でない関数には WorkflowRun を渡さない。

    回帰テスト: _invoke が WorkflowRun を pipeline 関数の config 引数に渡し、
    AttributeError: 'WorkflowRun' object has no attribute 'spotify' で
    クラッシュしていた問題を防止する。
    """

    class FakeConfig:
        spotify = "loaded"

    def pipeline_like_function(config=None):
        resolved = config or FakeConfig()
        return resolved.spotify

    run = _make_minimal_run()
    result = InProcessStepExecutor._invoke(pipeline_like_function, run)
    assert result == "loaded"


def test_invoke_passes_workflow_run_when_annotated():
    """第一引数が WorkflowRun 型の関数には WorkflowRun を渡す。"""
    received = {}

    def takes_workflow_run(run: WorkflowRun):
        received["run_id"] = run.run_id

    run = _make_minimal_run()
    InProcessStepExecutor._invoke(takes_workflow_run, run)
    assert received["run_id"] == run.run_id


def _make_minimal_run() -> WorkflowRun:
    """テスト用 WorkflowRun。"""
    return WorkflowRun(
        run_id="test-run-id",
        workflow_id="test_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
        status=WorkflowRunStatus.RUNNING,
        scheduled_at=None,
        queued_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        last_error_message=None,
        requested_by="test",
        parent_run_id=None,
        result_summary=None,
    )
