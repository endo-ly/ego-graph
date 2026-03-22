from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ingest.browser_history.schema import (
    BrowserHistoryIngestState,
    BrowserHistoryPayload,
)


def test_payload_accepts_valid_browser_history_request():
    payload = BrowserHistoryPayload.model_validate(
        {
            "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            "source_device": "home-windows-pc",
            "browser": "edge",
            "profile": "Default",
            "synced_at": "2026-03-22T12:00:00Z",
            "items": [
                {
                    "url": "https://example.com",
                    "visit_time": "2026-03-22T08:31:12Z",
                }
            ],
        }
    )

    assert payload.browser == "edge"
    assert payload.profile == "Default"


def test_payload_rejects_unknown_browser():
    with pytest.raises(ValidationError):
        BrowserHistoryPayload.model_validate(
            {
                "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
                "source_device": "home-windows-pc",
                "browser": "vivaldi",
                "profile": "Default",
                "synced_at": "2026-03-22T12:00:00Z",
                "items": [],
            }
        )


def test_state_schema_has_expected_shape():
    state = BrowserHistoryIngestState(
        sync_id="2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
        last_successful_sync_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        last_sync_status="events_saved",
        last_failure_code=None,
        last_received_at=datetime(2026, 3, 22, 12, 0, 1, tzinfo=timezone.utc),
        last_accepted_count=3,
    )

    assert state.last_sync_status == "events_saved"
    assert state.last_accepted_count == 3
