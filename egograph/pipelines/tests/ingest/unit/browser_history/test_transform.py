from datetime import datetime, timezone

from pipelines.sources.browser_history.schema import BrowserHistoryPayload
from pipelines.sources.browser_history.transform import (
    build_page_view_id,
    transform_payload_to_page_view_rows,
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
                }
            ],
        }
    )


def test_transform_item_to_event_row():
    rows = transform_payload_to_page_view_rows(
        _payload(),
        ingested_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    assert rows[0]["browser"] == "brave"
    assert rows[0]["profile"] == "Profile 1"
    assert rows[0]["url"] == "https://example.com"
    assert rows[0]["visit_span_count"] == 1


def test_transform_generates_stable_page_view_id():
    payload = _payload()
    item = payload.items[0]
    started_at = item.visit_time
    ended_at = item.visit_time

    page_view_id_1 = build_page_view_id(
        source_device=payload.source_device,
        browser=payload.browser,
        profile=payload.profile,
        url=item.url,
        started_at=started_at,
        ended_at=ended_at,
        transition=item.transition,
    )
    page_view_id_2 = build_page_view_id(
        source_device=payload.source_device,
        browser=payload.browser,
        profile=payload.profile,
        url=item.url,
        started_at=started_at,
        ended_at=ended_at,
        transition=item.transition,
    )

    assert page_view_id_1 == page_view_id_2


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

    rows = transform_payload_to_page_view_rows(payload)

    assert rows[0]["title"] is None
    assert rows[0]["transition"] is None


def test_transform_clusters_same_url_visits_within_two_seconds():
    payload = BrowserHistoryPayload.model_validate(
        {
            "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            "source_device": "device-1",
            "browser": "edge",
            "profile": "Default",
            "synced_at": "2026-03-22T12:00:00Z",
            "items": [
                {
                    "url": "https://example.com",
                    "visit_time": "2026-03-22T08:31:12Z",
                    "transition": "reload",
                },
                {
                    "url": "https://example.com",
                    "visit_time": "2026-03-22T08:31:13.900Z",
                    "transition": "link",
                },
            ],
        }
    )

    rows = transform_payload_to_page_view_rows(payload)

    assert len(rows) == 1
    assert rows[0]["visit_span_count"] == 2
    assert rows[0]["transition"] == "link"
    assert rows[0]["started_at_utc"].isoformat() == "2026-03-22T08:31:12+00:00"
    assert rows[0]["ended_at_utc"].isoformat() == "2026-03-22T08:31:13.900000+00:00"
