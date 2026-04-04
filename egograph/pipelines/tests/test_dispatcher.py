from pipelines.domain.workflow import (
    QueuedReason,
    StepDefinition,
    StepExecutorType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRunStatus,
)
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.repositories import WorkflowStateRepository
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.infrastructure.dispatching.lock_manager import WorkflowLockManager
from pipelines.infrastructure.dispatching.run_dispatcher import RunDispatcher
from pipelines.infrastructure.execution.inprocess_executor import InProcessStepExecutor
from pipelines.infrastructure.execution.log_store import LocalLogStore
from pipelines.infrastructure.execution.subprocess_executor import (
    SubprocessStepExecutor,
)


def _build_dispatcher(tmp_path, workflows):
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    repository = WorkflowStateRepository(conn)
    repository.register_workflows(workflows)
    log_store = LocalLogStore(tmp_path / "logs")
    dispatcher = RunDispatcher(
        repository=repository,
        workflows=workflows,
        lock_manager=WorkflowLockManager(conn, lease_seconds=60),
        subprocess_executor=SubprocessStepExecutor(log_store),
        inprocess_executor=InProcessStepExecutor(log_store),
        poll_seconds=0.01,
        heartbeat_seconds=60,
    )
    return repository, dispatcher


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
    repository, dispatcher = _build_dispatcher(tmp_path, workflows)
    run = repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    # Act
    dispatched = dispatcher.dispatch_once()
    updated_run = repository.get_run(run.run_id)
    steps = repository.list_step_runs(run.run_id)

    # Assert
    assert dispatched is True
    assert updated_run.status == WorkflowRunStatus.SUCCEEDED
    assert updated_run.result_summary == {"message": "ok"}
    assert len(steps) == 1
    assert steps[0].stdout_tail == "dummy step succeeded\n"
    assert steps[0].log_path is not None
    assert "dummy step succeeded" in LocalLogStore.read_log(steps[0].log_path)


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
    repository, dispatcher = _build_dispatcher(tmp_path, workflows)
    run = repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
    )

    # Act
    dispatcher.dispatch_once()
    updated_run = repository.get_run(run.run_id)
    steps = repository.list_step_runs(run.run_id)

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
    repository, dispatcher = _build_dispatcher(tmp_path, workflows)
    run = repository.enqueue_run(
        workflow_id="event_workflow",
        trigger_type=TriggerType.EVENT,
        queued_reason=QueuedReason.EVENT_ENQUEUE,
        result_summary={"compaction_targets": [{"year": 2026, "month": 4}]},
    )

    # Act
    dispatcher.dispatch_once()
    updated_run = repository.get_run(run.run_id)

    # Assert
    assert updated_run.status == WorkflowRunStatus.SUCCEEDED
    assert updated_run.result_summary == {
        "compaction_targets": [{"year": 2026, "month": 4}]
    }
