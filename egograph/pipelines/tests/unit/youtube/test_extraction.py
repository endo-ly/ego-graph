"""YouTube watch event 抽出ロジックの単体テスト。"""

from datetime import datetime, timezone

from pipelines.sources.youtube.extraction import extract_youtube_watch_events


def _row(
    *,
    page_view_id: str,
    transition: str | None = "link",
    url: str = "https://www.youtube.com/watch?v=video-1",
    title: str = "Sample Video - YouTube",
    sync_id: str = "sync-1",
) -> dict:
    return {
        "sync_id": sync_id,
        "page_view_id": page_view_id,
        "started_at_utc": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        "url": url,
        "title": title,
        "source_device": "desktop",
        "transition": transition,
        "ingested_at_utc": datetime(2026, 4, 21, 12, 5, tzinfo=timezone.utc),
    }


def test_excludes_reload_page_views():
    """transition='reload' の page_view は watch_event に変換されない。"""
    rows = [_row(page_view_id="pv-reload", transition="reload")]

    result = extract_youtube_watch_events(rows)

    assert result == []


def test_includes_link_typed_page_views():
    """transition='link' / 'typed' は通常通り watch_event になる。"""
    rows = [
        _row(page_view_id="pv-link", transition="link"),
        _row(
            page_view_id="pv-typed",
            transition="typed",
            url="https://www.youtube.com/watch?v=video-2",
        ),
    ]

    result = extract_youtube_watch_events(rows)

    assert len(result) == 2
    assert {event["source_event_id"] for event in result} == {"pv-link", "pv-typed"}


def test_mixed_input_filters_only_reload():
    """link/reload 混在入力で reload のみスキップされる。"""
    rows = [
        _row(page_view_id="pv-link-1", transition="link"),
        _row(page_view_id="pv-reload-1", transition="reload"),
        _row(
            page_view_id="pv-link-2",
            transition="link",
            url="https://www.youtube.com/watch?v=video-3",
        ),
        _row(page_view_id="pv-reload-2", transition="reload"),
    ]

    result = extract_youtube_watch_events(rows)

    assert [event["source_event_id"] for event in result] == ["pv-link-1", "pv-link-2"]


def test_no_transition_field_is_kept():
    """page_view に transition が無い場合 (後方互換) は除外しない。"""
    row = _row(page_view_id="pv-legacy")
    del row["transition"]

    result = extract_youtube_watch_events([row])

    assert len(result) == 1
    assert result[0]["source_event_id"] == "pv-legacy"
