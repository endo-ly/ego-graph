from datetime import UTC, datetime

from pipelines.domain.schedule import TriggerSpec, TriggerSpecType
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


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="dummy_workflow",
        name="Dummy workflow",
        description="Dummy workflow for tests",
        steps=(
            StepDefinition(
                step_id="step_1",
                step_name="Step 1",
                executor_type=StepExecutorType.INPROCESS,
                callable_ref="pipelines.tests.support.dummy_steps:succeed",
            ),
        ),
        triggers=(TriggerSpec(TriggerSpecType.INTERVAL, "6h"),),
    )


def test_register_workflows_and_enqueue_run(tmp_path):
    """workflow 定義同期と run enqueue ができる。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    repository = WorkflowStateRepository(conn)
    repository.register_workflows({"dummy_workflow": _workflow()})

    # Act
    run = repository.enqueue_run(
        workflow_id="dummy_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
        requested_by="api",
        scheduled_at=datetime(2026, 4, 4, tzinfo=UTC),
    )

    # Assert
    assert run.workflow_id == "dummy_workflow"
    assert run.status == WorkflowRunStatus.QUEUED
    assert run.requested_by == "api"
    assert repository.get_workflow("dummy_workflow")["enabled"] is True


def test_set_workflow_enabled_blocks_new_runs(tmp_path):
    """workflow 無効化後は新規 run を積めない。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    repository = WorkflowStateRepository(conn)
    repository.register_workflows({"dummy_workflow": _workflow()})

    # Act
    workflow = repository.set_workflow_enabled("dummy_workflow", False)

    # Assert
    assert workflow["enabled"] is False
    try:
        repository.enqueue_run(
            workflow_id="dummy_workflow",
            trigger_type=TriggerType.MANUAL,
            queued_reason=QueuedReason.MANUAL_REQUEST,
        )
    except Exception as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("disabled workflow accepted a new run")


def test_register_workflows_preserves_runtime_enabled_state(tmp_path):
    """registry 再同期で workflow_definitions.enabled を上書きしない。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    repository = WorkflowStateRepository(conn)
    repository.register_workflows({"dummy_workflow": _workflow()})
    repository.set_workflow_enabled("dummy_workflow", False)

    # Act
    repository.register_workflows({"dummy_workflow": _workflow()})

    # Assert
    assert repository.get_workflow("dummy_workflow")["enabled"] is False
