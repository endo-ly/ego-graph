"""Builtin workflow definitions."""

from __future__ import annotations

from pipelines.domain.schedule import MisfirePolicy, TriggerSpec, TriggerSpecType
from pipelines.domain.workflow import (
    StepDefinition,
    StepExecutorType,
    WorkflowDefinition,
)


def _inprocess_step(
    step_id: str,
    step_name: str,
    callable_ref: str,
    *,
    timeout_seconds: int = 1800,
    max_attempts: int = 1,
) -> StepDefinition:
    return StepDefinition(
        step_id=step_id,
        step_name=step_name,
        executor_type=StepExecutorType.INPROCESS,
        callable_ref=callable_ref,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


def _subprocess_step(
    step_id: str,
    step_name: str,
    command: tuple[str, ...],
    *,
    timeout_seconds: int = 1800,
    max_attempts: int = 1,
) -> StepDefinition:
    return StepDefinition(
        step_id=step_id,
        step_name=step_name,
        executor_type=StepExecutorType.SUBPROCESS,
        command=command,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


def get_workflows() -> dict[str, WorkflowDefinition]:
    """builtin workflow 定義を返す。"""
    workflows = [
        WorkflowDefinition(
            workflow_id="spotify_ingest_workflow",
            name="Spotify ingest workflow",
            description="Collect and compact Spotify datasets",
            steps=(
                _inprocess_step(
                    "run_spotify_ingest",
                    "Run Spotify ingest",
                    "pipelines.sources.spotify.pipeline:run_spotify_ingest",
                    timeout_seconds=1800,
                ),
                _inprocess_step(
                    "run_spotify_compact",
                    "Run Spotify compact",
                    "pipelines.sources.spotify.pipeline:run_spotify_compact",
                    timeout_seconds=1800,
                ),
            ),
            triggers=(
                TriggerSpec(TriggerSpecType.CRON, "0 22 * * *"),
                TriggerSpec(TriggerSpecType.CRON, "0 2 * * *"),
                TriggerSpec(TriggerSpecType.CRON, "0 6 * * *"),
                TriggerSpec(TriggerSpecType.CRON, "0 10 * * *"),
                TriggerSpec(TriggerSpecType.CRON, "0 14 * * *"),
            ),
            concurrency_key="spotify_ingest_workflow",
            timeout_seconds=3600,
            misfire_policy=MisfirePolicy.COALESCE_LATEST,
        ),
        WorkflowDefinition(
            workflow_id="github_ingest_workflow",
            name="GitHub ingest workflow",
            description="Collect and compact GitHub worklog datasets",
            steps=(
                _inprocess_step(
                    "run_github_ingest",
                    "Run GitHub ingest",
                    "pipelines.sources.github.pipeline:run_github_ingest",
                    timeout_seconds=1800,
                ),
                _inprocess_step(
                    "run_github_compact",
                    "Run GitHub compact",
                    "pipelines.sources.github.pipeline:run_github_compact",
                    timeout_seconds=1800,
                ),
            ),
            triggers=(TriggerSpec(TriggerSpecType.CRON, "0 15 * * *"),),
            concurrency_key="github_ingest_workflow",
            timeout_seconds=3600,
            misfire_policy=MisfirePolicy.COALESCE_LATEST,
        ),
        WorkflowDefinition(
            workflow_id="google_activity_ingest_workflow",
            name="Google Activity ingest workflow",
            description="Collect YouTube watch history from Google MyActivity",
            steps=(
                _inprocess_step(
                    "run_google_activity_ingest",
                    "Run Google Activity ingest",
                    "pipelines.sources.google_activity.main:main",
                    timeout_seconds=3600,
                ),
            ),
            triggers=(TriggerSpec(TriggerSpecType.CRON, "0 14 * * *"),),
            concurrency_key="google_activity_ingest_workflow",
            timeout_seconds=7200,
            misfire_policy=MisfirePolicy.COALESCE_LATEST,
        ),
        WorkflowDefinition(
            workflow_id="youtube_ingest_workflow",
            name="YouTube derived ingest workflow",
            description="Build YouTube watch events and masters from browser history",
            steps=(
                _inprocess_step(
                    "run_youtube_ingest",
                    "Run YouTube derived ingest",
                    "pipelines.sources.youtube.pipeline:run_youtube_ingest",
                    timeout_seconds=3600,
                ),
            ),
            triggers=(),
            concurrency_key="youtube_ingest_workflow",
            timeout_seconds=3600,
            misfire_policy=MisfirePolicy.SKIP_MISFIRE,
        ),
        WorkflowDefinition(
            workflow_id="local_mirror_sync_workflow",
            name="Local compacted parquet mirror sync",
            description="Sync compacted parquet files from R2 to local mirror",
            steps=(
                _inprocess_step(
                    "run_local_mirror_sync",
                    "Run local mirror sync",
                    "pipelines.sources.local_mirror_sync.pipeline:run_local_mirror_sync",
                    timeout_seconds=1800,
                ),
            ),
            triggers=(TriggerSpec(TriggerSpecType.INTERVAL, "6h"),),
            concurrency_key="local_mirror_sync_workflow",
            timeout_seconds=3600,
            misfire_policy=MisfirePolicy.COALESCE_LATEST,
        ),
        WorkflowDefinition(
            workflow_id="browser_history_compact_workflow",
            name="Browser history compact workflow",
            description=(
                "Compact browser history from events/ "
                "for maintenance/reprocessing"
            ),
            steps=(
                _inprocess_step(
                    "run_browser_history_compact",
                    "Run browser history compact for event targets",
                    "pipelines.sources.browser_history.pipeline:compact_from_event_context",
                    timeout_seconds=1800,
                ),
            ),
            triggers=(),
            concurrency_key="browser_history_compact_workflow",
            timeout_seconds=3600,
            misfire_policy=MisfirePolicy.SKIP_MISFIRE,
        ),
        WorkflowDefinition(
            workflow_id="browser_history_compact_maintenance_workflow",
            name="Browser history maintenance compact",
            description="Compact current and previous month browser history regularly",
            steps=(
                _inprocess_step(
                    "run_browser_history_compact_maintenance",
                    "Run browser history compact maintenance",
                    "pipelines.sources.browser_history.pipeline:"
                    "run_browser_history_compact_maintenance",
                    timeout_seconds=1800,
                ),
            ),
            triggers=(TriggerSpec(TriggerSpecType.INTERVAL, "6h"),),
            concurrency_key="browser_history_compact_workflow",
            timeout_seconds=3600,
            misfire_policy=MisfirePolicy.SKIP_MISFIRE,
        ),
    ]
    return {workflow.workflow_id: workflow for workflow in workflows}
