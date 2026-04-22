"""Step callable のエントリポイントテスト。"""

import inspect
from datetime import datetime, timezone

from pipelines.domain.workflow import (
    QueuedReason,
    TriggerType,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.infrastructure.execution.inprocess_executor import (
    InProcessStepExecutor,
)
from pipelines.sources.common.config import Config, DuckDBConfig, R2Config
from pipelines.sources.github.pipeline import run_github_compact, run_github_ingest
from pipelines.sources.spotify.pipeline import run_spotify_compact, run_spotify_ingest
from pipelines.sources.youtube.pipeline import run_youtube_ingest
from pipelines.workflows.registry import get_workflows
from pydantic import SecretStr


def _config() -> Config:
    return Config(
        duckdb=DuckDBConfig(
            r2=R2Config(
                endpoint_url="https://r2.example.com",
                access_key_id="access-key",
                secret_access_key=SecretStr("secret"),
                bucket_name="egograph",
            )
        )
    )


def test_run_spotify_ingest_delegates_to_existing_pipeline(monkeypatch):
    """Spotify ingest entrypoint は既存 pipeline 実装を呼ぶ。"""
    called = {}

    def fake_run_pipeline(config):
        called["config"] = config

    monkeypatch.setattr(
        "pipelines.sources.spotify.pipeline._run_ingest_pipeline",
        fake_run_pipeline,
    )

    result = run_spotify_ingest(_config())

    assert called["config"] == _config()
    assert result == {
        "provider": "spotify",
        "operation": "ingest",
        "status": "succeeded",
    }


def test_run_github_ingest_delegates_to_existing_pipeline(monkeypatch):
    """GitHub ingest entrypoint は既存 pipeline 実装を呼ぶ。"""
    called = {}

    def fake_run_pipeline(config):
        called["config"] = config

    monkeypatch.setattr(
        "pipelines.sources.github.pipeline._run_ingest_pipeline",
        fake_run_pipeline,
    )

    result = run_github_ingest(_config())

    assert called["config"] == _config()
    assert result == {
        "provider": "github",
        "operation": "ingest",
        "status": "succeeded",
    }


def test_run_youtube_ingest_skips_without_event_context():
    """YouTube ingest entrypoint は event context が無い場合 no-op で終わる。"""
    run = WorkflowRun(
        run_id="run-1",
        workflow_id="youtube_ingest_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
        status=WorkflowRunStatus.RUNNING,
        scheduled_at=None,
        queued_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        started_at=None,
        finished_at=None,
        last_error_message=None,
        requested_by="api",
        parent_run_id=None,
        result_summary=None,
    )

    result = run_youtube_ingest(run)

    assert result == {
        "provider": "youtube",
        "operation": "ingest",
        "status": "skipped",
        "reason": "missing_browser_history_event_context",
    }


def test_run_spotify_compact_returns_compacted_and_skipped_targets(monkeypatch):
    """Spotify compaction 結果を summary dict に整形する。"""
    calls = []

    class FakeStorage:
        def __init__(self, **kwargs):
            pass

        def compact_month(self, **kwargs):
            calls.append(kwargs)
            if kwargs["dataset_path"] == "spotify/artists":
                return None
            return f"compacted/{kwargs['dataset_path']}/data.parquet"

    monkeypatch.setattr(
        "pipelines.sources.spotify.pipeline.SpotifyStorage",
        FakeStorage,
    )

    result = run_spotify_compact(_config(), year=2026, month=4)

    assert len(calls) == 3
    assert result == {
        "provider": "spotify",
        "operation": "compact",
        "target_months": ["2026-04"],
        "compacted_keys": [
            "compacted/spotify/plays/data.parquet",
            "compacted/spotify/tracks/data.parquet",
        ],
        "skipped_targets": ["spotify/artists:2026-04"],
    }


def test_run_github_compact_raises_after_collecting_failures(monkeypatch):
    """GitHub compaction は失敗 dataset をまとめて RuntimeError にする。"""

    class FakeStorage:
        def __init__(self, **kwargs):
            pass

        def compact_month(self, **kwargs):
            if kwargs["dataset_path"] == "github/pull_requests":
                raise RuntimeError("boom")
            return "compacted/events/github/commits/year=2026/month=04/data.parquet"

    monkeypatch.setattr(
        "pipelines.sources.github.pipeline.GitHubWorklogStorage",
        FakeStorage,
    )

    try:
        run_github_compact(_config(), year=2026, month=4)
    except RuntimeError as exc:
        assert str(exc) == "GitHub compaction failed for: github/pull_requests:2026-04"
    else:
        raise AssertionError("RuntimeError was not raised")


def test_all_inprocess_steps_are_importable():
    """全 INPROCESS step の callable_ref が import 可能であることを検証する。"""
    workflows = get_workflows()
    refs = [
        step.callable_ref
        for wf in workflows.values()
        for step in wf.steps
        if step.callable_ref
    ]
    for ref in refs:
        InProcessStepExecutor._load_callable(ref)


def test_all_inprocess_steps_can_be_invoked_with_no_args():
    """InProcessStepExecutor._invoke は WorkflowRun 注入以外の step を引数ゼロで呼ぶ。

    各 callable が引数ゼロで実行可能であることを検証する。
    """
    workflows = get_workflows()
    for wf in workflows.values():
        for step in wf.steps:
            if not step.callable_ref:
                continue
            target = InProcessStepExecutor._load_callable(step.callable_ref)
            sig = inspect.signature(target)
            if not sig.parameters:
                continue
            first_param = next(iter(sig.parameters.values()))
            ann = first_param.annotation
            if ann is WorkflowRun or (isinstance(ann, str) and "WorkflowRun" in ann):
                continue
            sig.bind()
