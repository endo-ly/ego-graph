from datetime import UTC, datetime

from pipelines.domain.schedule import TriggerSpec, TriggerSpecType
from pipelines.domain.workflow import (
    StepDefinition,
    StepExecutorType,
    WorkflowDefinition,
)
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.run_repository import RunRepository
from pipelines.infrastructure.db.schedule_state_repository import (
    ScheduleStateRepository,
)
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.infrastructure.db.workflow_repository import WorkflowRepository
from pipelines.infrastructure.scheduling.apscheduler_app import ScheduleTriggerApp


def test_enqueue_schedule_run_ignores_disabled_workflow(tmp_path):
    """別プロセスで disable された workflow は schedule 発火時に no-op にする。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    workflow_repository = WorkflowRepository(conn)
    schedule_state_repository = ScheduleStateRepository(conn)
    run_repository = RunRepository(workflow_repository, conn)
    workflows = {
        "probe_workflow": WorkflowDefinition(
            workflow_id="probe_workflow",
            name="Probe workflow",
            description="Probe workflow",
            steps=(
                StepDefinition(
                    step_id="probe_step",
                    step_name="Probe step",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
            triggers=(TriggerSpec(TriggerSpecType.INTERVAL, "1s"),),
        )
    }
    scheduler = ScheduleTriggerApp(
        workflow_repository=workflow_repository,
        schedule_state_repository=schedule_state_repository,
        run_repository=run_repository,
        workflows=workflows,
        timezone="UTC",
    )
    scheduler.sync_jobs()
    workflow_repository.set_workflow_enabled("probe_workflow", False)

    # Act
    scheduler._enqueue_schedule_run("probe_workflow:0", "probe_workflow")

    # Assert
    workflow = workflow_repository.get_workflow("probe_workflow")
    assert run_repository.list_runs(workflow_id="probe_workflow") == []
    assert workflow["enabled"] is False
    assert workflow["schedules"][0]["next_run_at"] is None
    assert (
        datetime.fromisoformat(workflow["schedules"][0]["last_scheduled_at"]).tzinfo
        == UTC
    )


def test_schedule_run_preserves_trigger_input_and_name(tmp_path):
    """schedule固有のrun入力と識別名をqueueへ渡す。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    workflow_repository = WorkflowRepository(conn)
    schedule_state_repository = ScheduleStateRepository(conn)
    run_repository = RunRepository(workflow_repository, conn)
    trigger = TriggerSpec(
        TriggerSpecType.CRON,
        "30 4 * * *",
        schedule_name="google_health_daily_repair",
        result_summary={"request": {"repair_days": 14}},
        use_service_timezone=True,
    )
    workflows = {
        "probe_workflow": WorkflowDefinition(
            workflow_id="probe_workflow",
            name="Probe workflow",
            description="Probe workflow",
            steps=(
                StepDefinition(
                    step_id="probe_step",
                    step_name="Probe step",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
            triggers=(trigger,),
        )
    }
    scheduler = ScheduleTriggerApp(
        workflow_repository=workflow_repository,
        schedule_state_repository=schedule_state_repository,
        run_repository=run_repository,
        workflows=workflows,
        timezone="Asia/Tokyo",
    )

    # Act
    scheduler.sync_jobs()
    scheduler._enqueue_schedule_run(
        "probe_workflow:google_health_daily_repair",
        "probe_workflow",
        trigger.result_summary,
    )

    # Assert
    workflow = workflow_repository.get_workflow("probe_workflow")
    run = run_repository.list_runs(workflow_id="probe_workflow")[0]
    assert (
        workflow["schedules"][0]["schedule_id"]
        == "probe_workflow:google_health_daily_repair"
    )
    assert workflow["schedules"][0]["timezone"] == "TIMEZONE"
    assert run.result_summary == {"request": {"repair_days": 14}}
    job = scheduler._scheduler.get_job("probe_workflow:google_health_daily_repair")
    assert str(job.trigger.timezone) == "Asia/Tokyo"


def test_schedule_names_are_scoped_by_workflow(tmp_path):
    """同名scheduleを持つworkflowを独立したjobとして登録する。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    workflow_repository = WorkflowRepository(conn)
    schedule_state_repository = ScheduleStateRepository(conn)
    trigger = TriggerSpec(
        TriggerSpecType.INTERVAL,
        "1h",
        schedule_name="daily_repair",
    )
    workflows = {
        workflow_id: WorkflowDefinition(
            workflow_id=workflow_id,
            name=workflow_id,
            description=workflow_id,
            steps=(
                StepDefinition(
                    step_id="probe_step",
                    step_name="Probe step",
                    executor_type=StepExecutorType.INPROCESS,
                    callable_ref="pipelines.tests.support.dummy_steps:succeed",
                ),
            ),
            triggers=(trigger,),
        )
        for workflow_id in ("first_workflow", "second_workflow")
    }
    scheduler = ScheduleTriggerApp(
        workflow_repository=workflow_repository,
        schedule_state_repository=schedule_state_repository,
        run_repository=RunRepository(workflow_repository, conn),
        workflows=workflows,
        timezone="UTC",
    )

    # Act
    scheduler.sync_jobs()

    # Assert
    assert {job.id for job in scheduler._scheduler.get_jobs()} == {
        "first_workflow:daily_repair",
        "second_workflow:daily_repair",
    }
    assert {
        state.schedule_id for state in schedule_state_repository.get_schedule_states()
    } == {
        "first_workflow:daily_repair",
        "second_workflow:daily_repair",
    }
