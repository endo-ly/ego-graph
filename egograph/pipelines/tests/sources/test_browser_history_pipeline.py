"""Browser History source pipeline tests."""

from datetime import datetime, timezone
from uuid import UUID

from pipelines.domain.workflow import (
    QueuedReason,
    TriggerType,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.sources.browser_history.ingest_pipeline import (
    BrowserHistoryPipelineResult,
)
from pipelines.sources.browser_history.pipeline import (
    compact_from_event_context,
    enqueue_browser_history_compaction_event,
    run_browser_history_compact_maintenance,
    run_browser_history_ingest,
)
from pipelines.sources.browser_history.schema import BrowserHistoryPayload


def _payload() -> BrowserHistoryPayload:
    return BrowserHistoryPayload(
        sync_id=UUID("12345678-1234-5678-1234-567812345678"),
        source_device="desktop",
        browser="edge",
        profile="Default",
        synced_at=datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc),
        items=[],
    )


def test_enqueue_browser_history_compaction_event_returns_none_without_targets():
    """targets が空なら event enqueue を行わない。"""
    result = enqueue_browser_history_compaction_event((), lambda payload: "run-1")

    assert result is None


def test_enqueue_browser_history_compaction_event_builds_event_payload():
    """targets を event enqueue 用 payload に変換する。"""
    captured: dict[str, object] = {}

    def enqueue_run(payload):
        captured.update(payload)
        return "run-1"

    run_id = enqueue_browser_history_compaction_event(
        ((2026, 4), (2026, 3)),
        enqueue_run,
    )

    assert run_id == "run-1"
    assert captured == {
        "workflow_id": "browser_history_compact_workflow",
        "trigger_type": "event",
        "queued_reason": "event_enqueue",
        "payload": {
            "compaction_targets": [
                {"year": 2026, "month": 4},
                {"year": 2026, "month": 3},
            ],
        },
    }


def test_run_browser_history_ingest_returns_compact_run_id(monkeypatch):
    """ingest 成功後、compaction target があれば event run id を結果へ含める。"""
    expected_received_at = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)
    dummy_storage = object()

    monkeypatch.setattr(
        "pipelines.sources.browser_history.pipeline._resolve_browser_history_storage",
        lambda config, storage: dummy_storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.browser_history.pipeline.run_browser_history_pipeline",
        lambda payload, storage, received_at: BrowserHistoryPipelineResult(
            sync_id=str(payload.sync_id),
            accepted=2,
            raw_saved=True,
            events_saved=True,
            received_at=received_at,
            compaction_targets=((2026, 4),),
        ),
    )

    result = run_browser_history_ingest(
        _payload(),
        storage=dummy_storage,
        received_at=expected_received_at,
        enqueue_run=lambda _: "run-compact-1",
    )

    assert result.sync_id == "12345678-1234-5678-1234-567812345678"
    assert result.compaction_targets == ((2026, 4),)
    assert result.compact_run_id == "run-compact-1"
    assert result.to_summary_dict() == {
        "sync_id": "12345678-1234-5678-1234-567812345678",
        "accepted": 2,
        "raw_saved": True,
        "events_saved": True,
        "received_at": "2026-04-04T12:00:00+00:00",
        "compaction_targets": [{"year": 2026, "month": 4}],
        "compact_run_id": "run-compact-1",
    }


def test_run_browser_history_compact_maintenance_uses_previous_and_current_month(
    monkeypatch,
):
    """maintenance compact は前月+当月を対象にする。"""
    captured: dict[str, object] = {}

    def fake_run_compact(targets, *, config=None, storage=None):
        captured["targets"] = tuple(targets)
        captured["storage"] = storage
        return {"status": "ok"}

    monkeypatch.setattr(
        "pipelines.sources.browser_history.pipeline.run_browser_history_compact",
        fake_run_compact,
    )

    result = run_browser_history_compact_maintenance(
        storage=object(),
        now=datetime(2026, 4, 4, 0, 0, tzinfo=timezone.utc),
    )

    assert result == {"status": "ok"}
    assert captured["targets"] == ((2026, 3), (2026, 4))


def test_compact_from_event_context_uses_run_summary_targets(monkeypatch):
    """event run の compaction_targets から compact 対象月を復元する。"""
    captured: dict[str, object] = {}

    def fake_run_compact(targets, *, config=None, storage=None):
        captured["targets"] = tuple(targets)
        return {"status": "ok"}

    monkeypatch.setattr(
        "pipelines.sources.browser_history.pipeline.run_browser_history_compact",
        fake_run_compact,
    )
    run = WorkflowRun(
        run_id="run-1",
        workflow_id="browser_history_compact_workflow",
        trigger_type=TriggerType.EVENT,
        queued_reason=QueuedReason.EVENT_ENQUEUE,
        status=WorkflowRunStatus.RUNNING,
        scheduled_at=None,
        queued_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
        finished_at=None,
        last_error_message=None,
        requested_by="api",
        parent_run_id=None,
        result_summary={
            "compaction_targets": [
                {"year": 2026, "month": 4},
                {"year": 2026, "month": 3},
            ]
        },
    )

    result = compact_from_event_context(run)

    assert result == {"status": "ok"}
    assert captured["targets"] == ((2026, 4), (2026, 3))
