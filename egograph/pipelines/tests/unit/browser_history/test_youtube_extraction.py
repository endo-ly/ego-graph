"""YouTube watch event 抽出の単体テスト。"""

from datetime import datetime, timezone

from pipelines.sources.youtube.extraction import (
    detect_content_type,
    extract_video_id,
    extract_youtube_watch_events,
    group_watch_events_by_month,
    normalize_youtube_url,
)


def _page_view_row(
    url: str,
    *,
    title: str | None = "Some Video - YouTube",
    started_at: datetime | None = None,
) -> dict:
    """テスト用の page_view_row を生成する。"""
    return {
        "page_view_id": "browser_history_page_view_abc123",
        "started_at_utc": started_at
        or datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        "ended_at_utc": datetime(2026, 4, 21, 12, 5, tzinfo=timezone.utc),
        "url": url,
        "title": title,
        "browser": "edge",
        "profile": "Default",
        "source_device": "desktop-main",
        "transition": "link",
        "visit_span_count": 1,
        "synced_at_utc": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        "ingested_at_utc": datetime(2026, 4, 21, 12, 10, tzinfo=timezone.utc),
    }


# --- Test 1: watch?v= URL からの抽出 ---


def test_extract_watch_event_from_watch_url():
    """watch?v= URLから video_id と content_type=video を抽出できる。"""
    # Arrange
    rows = [_page_view_row("https://www.youtube.com/watch?v=dQw4w9WgXcQ")]

    # Act
    events = extract_youtube_watch_events(rows)

    # Assert
    assert len(events) == 1
    event = events[0]
    assert event["video_id"] == "dQw4w9WgXcQ"
    assert event["content_type"] == "video"
    assert event["video_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert event["video_title"] == "Some Video - YouTube"
    assert event["source"] == "browser_history"
    assert event["source_event_id"] == "browser_history_page_view_abc123"
    assert event["source_device"] == "desktop-main"
    assert event["channel_id"] is None
    assert event["channel_name"] is None
    assert isinstance(event["watch_event_id"], str)
    assert len(event["watch_event_id"]) > 0
    assert event["watched_at_utc"] == datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)


# --- Test 2: shorts/ URL からの抽出 ---


def test_extract_watch_event_from_shorts_url():
    """shorts/ URLから video_id と content_type=short を抽出できる。"""
    # Arrange
    rows = [_page_view_row("https://www.youtube.com/shorts/abc123xyz")]

    # Act
    events = extract_youtube_watch_events(rows)

    # Assert
    assert len(events) == 1
    assert events[0]["video_id"] == "abc123xyz"
    assert events[0]["content_type"] == "short"
    assert events[0]["video_url"] == "https://www.youtube.com/shorts/abc123xyz"


# --- Test 3: youtu.be/ 短縮URLの正規化 ---


def test_extract_watch_event_from_youtu_be_url():
    """youtu.be/ 短縮URLを正規URLに変換できる。"""
    # Arrange
    rows = [_page_view_row("https://youtu.be/dQw4w9WgXcQ")]

    # Act
    events = extract_youtube_watch_events(rows)

    # Assert
    assert len(events) == 1
    assert events[0]["video_id"] == "dQw4w9WgXcQ"
    assert events[0]["content_type"] == "video"
    assert events[0]["video_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# --- Test 4: watch対象外URLの除外 ---


def test_skip_non_watch_youtube_urls():
    """channel/playlist/feed/searchはwatch eventとして除外される。"""
    # Arrange
    non_watch_urls = [
        "https://www.youtube.com/@channelname",
        "https://www.youtube.com/channel/UCxxxxxx",
        "https://www.youtube.com/playlist?list=PLxxxxxx",
        "https://www.youtube.com/feed/trending",
        "https://www.youtube.com/results?search_query=test",
        "https://www.youtube.com/",
        "https://www.youtube.com",
        "https://m.youtube.com/",
        "https://www.youtube.com/c/channelname",
    ]
    rows = [_page_view_row(url) for url in non_watch_urls]

    # Act
    events = extract_youtube_watch_events(rows)

    # Assert
    assert len(events) == 0


# --- Test 5: title 欠落行の除外 ---


def test_require_title_in_browser_history_input():
    """title 欠落 payload は変換対象外。"""
    # Arrange
    rows = [
        _page_view_row(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title=None,
        ),
        _page_view_row(
            "https://www.youtube.com/watch?v=has_title",
            title="Has Title - YouTube",
        ),
    ]

    # Act
    events = extract_youtube_watch_events(rows)

    # Assert
    assert len(events) == 1
    assert events[0]["video_id"] == "has_title"
    assert events[0]["video_title"] == "Has Title - YouTube"


# --- Test 6: 月単位でのグルーピング ---


def test_group_events_by_month_for_youtube_storage():
    """抽出済み watch event が月単位で保存対象に分配される。"""
    # Arrange
    jan = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    feb = datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc)
    feb_late = datetime(2026, 2, 28, 23, 0, tzinfo=timezone.utc)
    rows = [
        _page_view_row("https://www.youtube.com/watch?v=jan_video", started_at=jan),
        _page_view_row("https://www.youtube.com/watch?v=feb_video1", started_at=feb),
        _page_view_row(
            "https://www.youtube.com/watch?v=feb_video2", started_at=feb_late
        ),
    ]
    events = extract_youtube_watch_events(rows)

    # Act
    grouped = group_watch_events_by_month(events)

    # Assert
    assert (2026, 1) in grouped
    assert (2026, 2) in grouped
    assert len(grouped[(2026, 1)]) == 1
    assert len(grouped[(2026, 2)]) == 2
    assert grouped[(2026, 1)][0]["video_id"] == "jan_video"


# --- 補助関数の単体テスト ---


def test_normalize_youtube_url_converts_youtu_be():
    """youtu.be URLを正規watch URLに変換する。"""
    assert (
        normalize_youtube_url("https://youtu.be/abc123")
        == "https://www.youtube.com/watch?v=abc123"
    )


def test_normalize_youtube_url_returns_none_for_non_youtube():
    """非YouTube URLはNoneを返す。"""
    assert normalize_youtube_url("https://example.com") is None


def test_normalize_youtube_url_preserves_watch_url():
    """watch URLはそのまま返す。"""
    url = "https://www.youtube.com/watch?v=abc123"
    assert normalize_youtube_url(url) == url


def test_extract_video_id_handles_query_params():
    """追加クエリパラメータ付きURLからvideo_idを抽出する。"""
    assert extract_video_id("https://www.youtube.com/watch?v=abc123&t=42") == "abc123"


def test_detect_content_type_returns_short_for_shorts():
    """shorts URL に対して 'short' を返す。"""
    assert detect_content_type("https://www.youtube.com/shorts/abc") == "short"


def test_detect_content_type_returns_video_for_watch():
    """watch URL に対して 'video' を返す。"""
    assert detect_content_type("https://www.youtube.com/watch?v=abc") == "video"


def test_extract_youtube_watch_events_with_youtu_be_query_params():
    """youtu.be URLにクエリパラメータが含まれていても正しく抽出する。"""
    # Arrange
    rows = [_page_view_row("https://youtu.be/xyz789?t=10")]

    # Act
    events = extract_youtube_watch_events(rows)

    # Assert
    assert len(events) == 1
    assert events[0]["video_id"] == "xyz789"
    assert events[0]["video_url"] == "https://www.youtube.com/watch?v=xyz789"
