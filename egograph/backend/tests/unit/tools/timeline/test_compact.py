"""Daily Timeline の MCP compact 表現を検証する。"""

from backend.domain.tools.timeline.compact import compact_daily_timeline


def test_compact_daily_timeline_omits_metadata_empty_values_and_duplicate_times():
    """metadata・空値・UTC/local重複を除き、有効なゼロ値を残す。"""
    response = {
        "date": "2026-06-28",
        "timezone": "Asia/Tokyo",
        "range": {
            "start_local": "2026-06-28T00:00:00+09:00",
            "end_local": "2026-06-29T00:00:00+09:00",
            "start_utc": "2026-06-27T15:00:00Z",
            "end_utc": "2026-06-28T15:00:00Z",
        },
        "items": [
            {
                "event_id": "spotify:play:p1",
                "source": "spotify",
                "kind": "music_play",
                "started_at_utc": "2026-06-28T00:12:03Z",
                "started_at_local": "2026-06-28T09:12:03+09:00",
                "ended_at_utc": None,
                "ended_at_local": None,
                "duration_seconds": 0,
                "title": "Song",
                "subtitle": "",
                "url": None,
                "metadata": {"track_id": "t1"},
            }
        ],
        "correlations": [],
        "gaps": [
            {
                "gap_id": "gap_1",
                "kind": "no_observed_events_gap",
                "start_utc": "2026-06-28T01:00:00Z",
                "end_utc": "2026-06-28T03:00:00Z",
                "start_local": "2026-06-28T10:00:00+09:00",
                "end_local": "2026-06-28T12:00:00+09:00",
                "duration_minutes": 120,
                "preceded_by_event_id": "spotify:play:p1",
                "followed_by_event_id": "github:commit:c1",
            }
        ],
        "daily_summaries": {},
        "coverage": {
            "spotify": {"included": True, "event_count": 1},
            "youtube": {"included": False, "event_count": 0, "status": "excluded"},
        },
        "meta": {"item_count": 1, "truncated": False, "generated_at": "now"},
    }

    compact = compact_daily_timeline(response)

    assert compact == {
        "date": "2026-06-28",
        "timezone": "Asia/Tokyo",
        "range": {
            "start": "2026-06-28T00:00:00+09:00",
            "end": "2026-06-29T00:00:00+09:00",
        },
        "items": [
            {
                "event_id": "spotify:play:p1",
                "started_at": "2026-06-28T09:12:03+09:00",
                "source": "spotify",
                "kind": "music_play",
                "duration_seconds": 0,
                "title": "Song",
            }
        ],
        "gaps": [
            {
                "gap_id": "gap_1",
                "kind": "no_observed_events_gap",
                "start": "2026-06-28T10:00:00+09:00",
                "end": "2026-06-28T12:00:00+09:00",
                "duration_minutes": 120,
                "preceded_by_event_id": "spotify:play:p1",
                "followed_by_event_id": "github:commit:c1",
            }
        ],
        "coverage": {
            "spotify": {"included": True, "event_count": 1},
            "youtube": {"included": False, "event_count": 0, "status": "excluded"},
        },
        "meta": {
            "item_count": 1,
            "truncated": False,
            "generated_at": "now",
            "format": "compact",
        },
    }


def test_compact_daily_timeline_preserves_raw_ref_when_requested():
    """明示的に要求された raw_ref は metadata と分けて保持する。"""
    response = {
        "items": [
            {
                "event_id": "spotify:play:p1",
                "started_at_local": "2026-06-28T09:12:03+09:00",
                "raw_ref": {
                    "dataset_id": "spotify.plays",
                    "record_id": "p1",
                    "timestamp_column": "played_at_utc",
                },
                "metadata": {"track_id": "t1"},
            }
        ],
        "meta": {},
    }

    compact = compact_daily_timeline(response)

    assert compact["items"][0]["raw_ref"] == {
        "dataset_id": "spotify.plays",
        "record_id": "p1",
        "timestamp_column": "played_at_utc",
    }
    assert "metadata" not in compact["items"][0]
