from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pipelines.sources.browser_history.pipeline import run_browser_history_pipeline
from pipelines.sources.browser_history.schema import BrowserHistoryPayload


def _payload(items: list[dict] | None = None) -> BrowserHistoryPayload:
    return BrowserHistoryPayload.model_validate(
        {
            "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            "source_device": "device-1",
            "browser": "edge",
            "profile": "Default",
            "synced_at": "2026-03-22T12:00:00Z",
            "items": items
            if items is not None
            else [
                {
                    "url": "https://example.com",
                    "visit_time": "2026-03-22T08:31:12Z",
                }
            ],
        }
    )


def test_pipeline_success_path():
    storage = MagicMock()
    storage.save_raw_json.return_value = "raw/key.json"
    storage.save_parquet.return_value = "events/key.parquet"

    result = run_browser_history_pipeline(
        _payload(),
        storage,
        received_at=datetime(2026, 3, 22, 12, 0, 1, tzinfo=timezone.utc),
    )

    assert result.accepted == 1
    assert result.raw_saved is True
    assert result.events_saved is True
    assert result.compaction_targets == ((2026, 3),)
    storage.save_state.assert_called_once()


def test_pipeline_raises_when_raw_save_fails():
    storage = MagicMock()
    storage.save_raw_json.return_value = None

    with pytest.raises(RuntimeError, match="raw browser history payload"):
        run_browser_history_pipeline(_payload(), storage)

    storage.save_state.assert_not_called()


def test_pipeline_raises_when_events_save_fails():
    storage = MagicMock()
    storage.save_raw_json.return_value = "raw/key.json"
    storage.save_parquet.return_value = None

    with pytest.raises(RuntimeError, match="Failed to save browser history events"):
        run_browser_history_pipeline(_payload(), storage)

    storage.save_state.assert_not_called()


def test_pipeline_returns_accepted_count_for_empty_sync():
    storage = MagicMock()

    result = run_browser_history_pipeline(_payload(items=[]), storage)

    assert result.accepted == 0
    assert result.raw_saved is False
    assert result.events_saved is False
    assert result.compaction_targets == ()
    storage.save_state.assert_called_once()
