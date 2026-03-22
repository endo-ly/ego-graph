from datetime import datetime, timezone

from ingest.browser_history.schema import BrowserHistoryPayload
from ingest.browser_history.transform import (
    build_event_id,
    transform_payload_to_event_rows,
)


def _payload() -> BrowserHistoryPayload:
    return BrowserHistoryPayload.model_validate(
        {
            "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            "source_device": "device-1",
            "browser": "brave",
            "profile": "Profile 1",
            "synced_at": "2026-03-22T12:00:00Z",
            "items": [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "visit_time": "2026-03-22T08:31:12Z",
                    "visit_id": "12345",
                    "referring_visit_id": "12344",
                    "transition": "link",
                    "visit_count": 3,
                }
            ],
        }
    )


def test_transform_item_to_event_row():
    rows = transform_payload_to_event_rows(
        _payload(),
        ingested_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    assert rows[0]["browser"] == "brave"
    assert rows[0]["profile"] == "Profile 1"
    assert rows[0]["url"] == "https://example.com"


def test_transform_generates_stable_event_id():
    payload = _payload()
    item = payload.items[0]

    event_id_1 = build_event_id(
        source_device=payload.source_device,
        browser=payload.browser,
        profile=payload.profile,
        item=item,
    )
    event_id_2 = build_event_id(
        source_device=payload.source_device,
        browser=payload.browser,
        profile=payload.profile,
        item=item,
    )

    assert event_id_1 == event_id_2


def test_transform_handles_missing_optional_fields():
    payload = BrowserHistoryPayload.model_validate(
        {
            "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            "source_device": "device-1",
            "browser": "chrome",
            "profile": "Default",
            "synced_at": "2026-03-22T12:00:00Z",
            "items": [
                {
                    "url": "https://example.com/minimal",
                    "visit_time": "2026-03-22T08:31:12Z",
                }
            ],
        }
    )

    rows = transform_payload_to_event_rows(payload)

    assert rows[0]["title"] is None
    assert rows[0]["visit_id"] is None
