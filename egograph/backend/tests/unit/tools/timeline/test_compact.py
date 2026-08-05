"""Daily Timeline の MCP compact 表現を検証する。"""

from backend.domain.tools.timeline.compact import compact_daily_timeline


def test_compact_daily_timeline_omits_metadata_ids_empty_values_and_duplicate_times():
    """metadata・イベントID・空値・UTC/local重複を除き、有効なゼロ値を残す。"""
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
                "event_id": "spotify:play:sha256-64-chars",
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
        "correlations": [
            {
                "correlation_id": "corr_browser_history_youtube_001",
                "kind": "same_activity_candidate",
                "event_ids": [
                    "browser_history:page_view:sha256-a",
                    "youtube:watch_event:sha256-b",
                ],
                "confidence": 0.95,
                "reason": "same_youtube_video_url_within_120_seconds",
            }
        ],
        "gaps": [
            {
                "gap_id": "gap_1",
                "kind": "no_observed_events_gap",
                "start_utc": "2026-06-28T01:00:00Z",
                "end_utc": "2026-06-28T03:00:00Z",
                "start_local": "2026-06-28T10:00:00+09:00",
                "end_local": "2026-06-28T12:00:00+09:00",
                "duration_minutes": 120,
                "preceded_by_event_id": "spotify:play:sha256-a",
                "followed_by_event_id": "github:commit:sha256-b",
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
                "started_at": "2026-06-28T09:12:03+09:00",
                "source": "spotify",
                "kind": "music_play",
                "duration_seconds": 0,
                "title": "Song",
            }
        ],
        "correlations": [
            {
                "correlation_id": "corr_browser_history_youtube_001",
                "kind": "same_activity_candidate",
                "confidence": 0.95,
                "reason": "same_youtube_video_url_within_120_seconds",
            }
        ],
        "gaps": [
            {
                "gap_id": "gap_1",
                "kind": "no_observed_events_gap",
                "start": "2026-06-28T10:00:00+09:00",
                "end": "2026-06-28T12:00:00+09:00",
                "duration_minutes": 120,
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
                "event_id": "spotify:play:sha256-64-chars",
                "started_at_local": "2026-06-28T09:12:03+09:00",
                "raw_ref": {
                    "dataset_id": "spotify.plays",
                    "record_id": "sha256-64-chars",
                    "timestamp_column": "played_at_utc",
                },
                "metadata": {"track_id": "t1"},
            }
        ],
        "meta": {},
    }

    compact = compact_daily_timeline(response)

    assert "event_id" not in compact["items"][0]
    assert compact["items"][0]["raw_ref"] == {
        "dataset_id": "spotify.plays",
        "record_id": "sha256-64-chars",
        "timestamp_column": "played_at_utc",
    }
    assert "metadata" not in compact["items"][0]
