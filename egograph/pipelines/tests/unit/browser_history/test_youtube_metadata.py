"""YouTube メタデータ解決・マスター保存の単体テスト。"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from pipelines.sources.youtube.metadata import (
    build_channel_master_rows,
    build_video_master_rows,
    enrich_watch_events_with_metadata,
    resolve_youtube_metadata,
    save_youtube_masters,
)


def _api_video_response(
    video_id: str = "dQw4w9WgXcQ",
    title: str = "Rick Astley - Never Gonna Give You Up",
    channel_id: str = "UCuAXFkgsw1L7xaCfnd5JJOw",
    channel_title: str = "Rick Astley",
) -> dict:
    """テスト用の YouTube API video レスポンスを生成する。"""
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "channelId": channel_id,
            "channelTitle": channel_title,
            "publishedAt": "2009-10-25T06:57:33Z",
            "thumbnails": {"high": {"url": f"https://img.youtube.com/{video_id}.jpg"}},
            "description": "The official video.",
        },
        "contentDetails": {"duration": "PT3M33S"},
        "statistics": {"viewCount": "1500000000"},
    }


def _api_channel_response(
    channel_id: str = "UCuAXFkgsw1L7xaCfnd5JJOw",
    title: str = "Rick Astley",
) -> dict:
    """テスト用の YouTube API channel レスポンスを生成する。"""
    return {
        "id": channel_id,
        "snippet": {
            "title": title,
            "publishedAt": "2006-01-01T00:00:00Z",
            "thumbnails": {
                "high": {"url": f"https://img.youtube.com/ch/{channel_id}.jpg"}
            },
            "description": "Official channel.",
            "country": "GB",
        },
        "statistics": {"subscriberCount": "7000000", "videoCount": "100"},
    }


def _watch_event(
    video_id: str = "dQw4w9WgXcQ",
    *,
    video_title: str = "Rick Astley - Never Gonna Give You Up - YouTube",
    channel_id: str | None = None,
    channel_name: str | None = None,
) -> dict:
    """テスト用の watch event を生成する。"""
    return {
        "watch_event_id": "youtube_watch_event_abc123",
        "watched_at_utc": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "video_title": video_title,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "content_type": "video",
        "source": "browser_history",
        "source_event_id": "browser_history_page_view_001",
        "source_device": "desktop-main",
        "ingested_at_utc": datetime(2026, 4, 21, 12, 10, tzinfo=timezone.utc),
    }


# --- Test 1: YouTubeAPIClient.get_videos が呼ばれること ---


def test_reuse_youtube_api_client_for_video_metadata():
    """YouTubeAPIClient.get_videos が抽出済み video_id で呼ばれる。"""
    # Arrange
    events = [_watch_event("vid1"), _watch_event("vid2")]
    mock_client = MagicMock()
    mock_client.get_videos.return_value = [
        _api_video_response("vid1"),
        _api_video_response("vid2"),
    ]
    mock_client.get_channels.return_value = [
        _api_channel_response("UCuAXFkgsw1L7xaCfnd5JJOw"),
    ]

    # Act
    result = resolve_youtube_metadata(events, mock_client)

    # Assert
    assert result is not None
    mock_client.get_videos.assert_called_once()
    called_video_ids = sorted(mock_client.get_videos.call_args[0][0])
    assert called_video_ids == ["vid1", "vid2"]


# --- Test 2: video master 行の構築 ---


def test_build_video_master_rows_from_api_response():
    """API レスポンスから video master 行が正しいカラムで構築される。"""
    # Arrange
    api_videos = [_api_video_response()]
    content_type_map = {"dQw4w9WgXcQ": "video"}

    # Act
    rows = build_video_master_rows(api_videos, content_type_map)

    # Assert
    assert len(rows) == 1
    row = rows[0]
    expected_keys = {
        "video_id",
        "title",
        "channel_id",
        "channel_name",
        "duration_seconds",
        "view_count",
        "like_count",
        "comment_count",
        "published_at",
        "thumbnail_url",
        "description",
        "category_id",
        "tags",
        "content_type",
        "updated_at",
    }
    assert set(row.keys()) == expected_keys
    assert row["video_id"] == "dQw4w9WgXcQ"
    assert row["title"] == "Rick Astley - Never Gonna Give You Up"
    assert row["channel_id"] == "UCuAXFkgsw1L7xaCfnd5JJOw"
    assert row["channel_name"] == "Rick Astley"
    assert row["content_type"] == "video"
    assert isinstance(row["updated_at"], datetime)


# --- Test 3: channel master 行の構築 ---


def test_build_channel_master_rows_from_api_response():
    """API レスポンスから channel master 行が正しいカラムで構築される。"""
    # Arrange
    api_channels = [_api_channel_response()]

    # Act
    rows = build_channel_master_rows(api_channels)

    # Assert
    assert len(rows) == 1
    row = rows[0]
    expected_keys = {
        "channel_id",
        "channel_name",
        "subscriber_count",
        "video_count",
        "view_count",
        "published_at",
        "thumbnail_url",
        "description",
        "country",
        "updated_at",
    }
    assert set(row.keys()) == expected_keys
    assert row["channel_id"] == "UCuAXFkgsw1L7xaCfnd5JJOw"
    assert row["channel_name"] == "Rick Astley"
    assert isinstance(row["updated_at"], datetime)


# --- Test 4: watch event へのメタデータ反映 ---


def test_fill_watch_event_metadata_from_video_master():
    """watch event に video_title, channel_id, channel_name が反映される。"""
    # Arrange
    events = [
        _watch_event("vid1", video_title="vid1 - YouTube"),
        _watch_event("vid2", video_title="vid2 - YouTube"),
    ]
    video_master = [
        {
            "video_id": "vid1",
            "title": "API Title 1",
            "channel_id": "ch1",
            "channel_name": "Channel One",
            "content_type": "video",
            "updated_at": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        },
        {
            "video_id": "vid2",
            "title": "API Title 2",
            "channel_id": "ch2",
            "channel_name": "Channel Two",
            "content_type": "short",
            "updated_at": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        },
    ]

    # Act
    enriched = enrich_watch_events_with_metadata(events, video_master, [])

    # Assert
    assert len(enriched) == 2
    assert enriched[0]["video_title"] == "API Title 1"
    assert enriched[0]["channel_id"] == "ch1"
    assert enriched[0]["channel_name"] == "Channel One"
    assert enriched[1]["video_title"] == "API Title 2"
    assert enriched[1]["channel_id"] == "ch2"
    assert enriched[1]["channel_name"] == "Channel Two"


# --- Test 5: API エラー時は None を返す ---


def test_fail_pipeline_when_metadata_resolution_is_unavailable():
    """YouTubeAPIClient が例外を投げた場合、resolve は None を返す。"""
    # Arrange
    events = [_watch_event()]
    mock_client = MagicMock()
    mock_client.get_videos.side_effect = RuntimeError("API quota exceeded")

    # Act
    result = resolve_youtube_metadata(events, mock_client)

    # Assert
    assert result is None


# --- Test 6: video / channel master parquet 保存 ---


def test_save_video_and_channel_master_parquet():
    """video と channel の master parquet が storage 経由で保存される。"""
    # Arrange
    mock_storage = MagicMock()
    mock_storage.save_video_master.return_value = "videos/key.parquet"
    mock_storage.save_channel_master.return_value = "channels/key.parquet"
    video_rows = [{"video_id": "v1", "updated_at": "2026-04-21"}]
    channel_rows = [{"channel_id": "ch1", "updated_at": "2026-04-21"}]

    # Act
    success = save_youtube_masters(
        mock_storage,
        video_rows,
        channel_rows,
        sync_id="sync-1",
    )

    # Assert
    assert success is True
    mock_storage.save_video_master.assert_called_once()
    mock_storage.save_channel_master.assert_called_once()


# --- Test 7: 全出力保存後にのみ state 更新対象としてイベントが返る ---


def test_resolve_youtube_metadata_returns_enriched_events_and_masters():
    """resolve成功時にenriched eventsとmasterが返ることを検証。"""
    # Arrange
    events = [_watch_event("vid1"), _watch_event("vid2")]
    mock_client = MagicMock()
    mock_client.get_videos.return_value = [
        _api_video_response("vid1"),
        _api_video_response("vid2"),
    ]
    mock_client.get_channels.return_value = [
        _api_channel_response(),
    ]

    # Act
    result = resolve_youtube_metadata(events, mock_client)

    # Assert
    assert result is not None
    enriched_events, video_master, channel_master = result
    # enriched events が metadata を持っている
    assert all(e["channel_id"] is not None for e in enriched_events)
    assert all(e["channel_name"] is not None for e in enriched_events)
    # video master と channel master が生成されている
    assert len(video_master) > 0
    assert len(channel_master) > 0
