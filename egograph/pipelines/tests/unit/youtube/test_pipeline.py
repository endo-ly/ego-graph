"""YouTube derived pipeline の単体テスト。"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from pipelines.domain.workflow import (
    QueuedReason,
    TriggerType,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.sources.youtube.pipeline import run_youtube_ingest


def _run(summary: dict | None) -> WorkflowRun:
    return WorkflowRun(
        run_id="run-1",
        workflow_id="youtube_ingest_workflow",
        trigger_type=TriggerType.EVENT,
        queued_reason=QueuedReason.EVENT_ENQUEUE,
        status=WorkflowRunStatus.RUNNING,
        scheduled_at=None,
        queued_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        finished_at=None,
        last_error_message=None,
        requested_by="api",
        parent_run_id=None,
        result_summary=summary,
    )


def test_run_youtube_ingest_skips_without_target_months():
    """event summary が不足している場合は no-op で終わる。"""
    result = run_youtube_ingest(_run({"sync_id": "sync-1"}))

    assert result["status"] == "skipped"
    assert result["reason"] == "missing_browser_history_event_context"


def test_run_youtube_ingest_processes_browser_history_sync(monkeypatch):
    """browser_history sync_id 単位で watch events を構築して保存する。"""
    fake_storage = MagicMock()
    fake_storage.is_sync_processed.return_value = False
    fake_storage.load_browser_history_page_views.return_value = [
        {
            "sync_id": "sync-1",
            "page_view_id": "pv-1",
            "started_at_utc": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
            "url": "https://www.youtube.com/watch?v=video-1",
            "title": "Video 1 - YouTube",
            "source_device": "desktop",
            "ingested_at_utc": datetime(2026, 4, 21, 12, 5, tzinfo=timezone.utc),
        }
    ]
    fake_storage.save_watch_events.return_value = "events/key.parquet"
    fake_storage.save_video_master.return_value = "master/videos.parquet"
    fake_storage.save_channel_master.return_value = "master/channels.parquet"

    fake_client = MagicMock()
    fake_client.get_videos.return_value = [
        {
            "id": "video-1",
            "snippet": {
                "title": "API Video 1",
                "channelId": "channel-1",
                "channelTitle": "Channel 1",
                "publishedAt": "2024-01-01T00:00:00Z",
                "thumbnails": {"high": {"url": "thumb.jpg"}},
            },
            "contentDetails": {"duration": "PT1M"},
            "statistics": {"viewCount": "100"},
        }
    ]
    fake_client.get_channels.return_value = [
        {
            "id": "channel-1",
            "snippet": {
                "title": "Channel 1",
                "publishedAt": "2020-01-01T00:00:00Z",
                "thumbnails": {"high": {"url": "channel.jpg"}},
            },
            "statistics": {"subscriberCount": "50", "videoCount": "3"},
        }
    ]

    monkeypatch.setattr(
        "pipelines.sources.youtube.pipeline._resolve_storage",
        lambda config: fake_storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.youtube.pipeline._resolve_api_client",
        lambda config: fake_client,
    )

    result = run_youtube_ingest(
        _run(
            {
                "sync_id": "sync-1",
                "target_months": [{"year": 2026, "month": 4}],
            }
        )
    )

    assert result["status"] == "succeeded"
    assert result["watch_event_count"] == 1
    fake_client.get_videos.assert_called_once_with(["video-1"])
    fake_client.get_channels.assert_called_once_with(["channel-1"])
    fake_storage.save_watch_events.assert_called_once()
    saved_watch_events = fake_storage.save_watch_events.call_args.args[0]
    assert saved_watch_events[0]["video_title"] == "API Video 1"
    assert saved_watch_events[0]["channel_id"] == "channel-1"
    assert saved_watch_events[0]["channel_name"] == "Channel 1"
    fake_storage.save_video_master.assert_called_once()
    fake_storage.save_channel_master.assert_called_once()
    fake_storage.mark_sync_processed.assert_called_once()


def test_run_youtube_ingest_skips_invalid_request_payload():
    """sync_id や month が不正な payload は skip する。"""
    result = run_youtube_ingest(
        _run(
            {
                "sync_id": "   ",
                "target_months": [
                    {"year": 2026, "month": 13},
                    {"year": -1, "month": 4},
                ],
            }
        )
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "missing_browser_history_event_context"
