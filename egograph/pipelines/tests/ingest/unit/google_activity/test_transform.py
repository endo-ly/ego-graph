from datetime import datetime, timezone

from pipelines.sources.google_activity.transform import (
    transform_channel_info,
    transform_video_info,
    transform_watch_history_item,
    transform_watch_history_items,
)


class TestTransformWatchHistoryItem:
    """transform_watch_history_itemのテスト。"""

    def test_transform_watch_history_item_success(self):
        """正常ケース: 必須フィールドすべて揃っている場合。"""
        watched_at = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        item = {
            "video_id": "abc123",
            "title": "Test Video",
            "channel_name": "Test Channel",
            "watched_at": watched_at,
            "video_url": "https://www.youtube.com/watch?v=abc123",
        }

        result = transform_watch_history_item(item, "account1")

        assert result is not None
        assert result["watch_id"] is not None
        assert len(result["watch_id"]) == 16  # sha256 hash[:16]
        assert result["account_id"] == "account1"
        assert result["watched_at_utc"] == watched_at
        assert result["video_id"] == "abc123"
        assert result["video_title"] == "Test Video"
        assert result["channel_id"] is None  # Not in MyActivity data
        assert result["channel_name"] == "Test Channel"
        assert result["video_url"] == "https://www.youtube.com/watch?v=abc123"
        assert result["context"] is None  # Optional field

    def test_transform_watch_history_item_missing_required_fields(self):
        """異常ケース: 必須フィールドが欠けている場合。"""
        item = {
            "video_id": "abc123",
            "title": "Test Video",
            # Missing channel_name
            # Missing watched_at
        }

        result = transform_watch_history_item(item, "account1")

        assert result is None

    def test_transform_watch_history_item_watch_id_consistency(self):
        """watch_idの一貫性テスト: 同じ入力で同じIDが生成されること。"""
        watched_at = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        item = {
            "video_id": "xyz789",
            "title": "Video",
            "channel_name": "Channel",
            "watched_at": watched_at,
            "video_url": "https://www.youtube.com/watch?v=xyz789",
        }

        result1 = transform_watch_history_item(item, "account1")
        result2 = transform_watch_history_item(item, "account1")

        assert result1["watch_id"] == result2["watch_id"]

    def test_transform_watch_history_item_different_accounts(self):
        """異なるアカウントで異なるwatch_idが生成されること。"""
        watched_at = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        item = {
            "video_id": "xyz789",
            "title": "Video",
            "channel_name": "Channel",
            "watched_at": watched_at,
            "video_url": "https://www.youtube.com/watch?v=xyz789",
        }

        result1 = transform_watch_history_item(item, "account1")
        result2 = transform_watch_history_item(item, "account2")

        assert result1["watch_id"] != result2["watch_id"]
        assert result1["account_id"] == "account1"
        assert result2["account_id"] == "account2"

    def test_transform_watch_history_item_empty_video_id(self):
        """video_idが空の場合はNoneを返すこと。"""
        watched_at = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        item = {
            "video_id": "",
            "title": "Test Video",
            "channel_name": "Test Channel",
            "watched_at": watched_at,
            "video_url": "https://www.youtube.com/watch?v=abc123",
        }

        result = transform_watch_history_item(item, "account1")

        assert result is None


class TestTransformWatchHistoryItems:
    """transform_watch_history_itemsのテスト。"""

    def test_transform_watch_history_items_success(self):
        """正常ケース: 複数アイテムを変換すること。"""
        watched_at1 = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)
        watched_at2 = datetime(2024, 1, 16, 14, 20, 30, tzinfo=timezone.utc)

        items = [
            {
                "video_id": "abc123",
                "title": "Video 1",
                "channel_name": "Channel 1",
                "watched_at": watched_at1,
                "video_url": "https://www.youtube.com/watch?v=abc123",
            },
            {
                "video_id": "xyz789",
                "title": "Video 2",
                "channel_name": "Channel 2",
                "watched_at": watched_at2,
                "video_url": "https://www.youtube.com/watch?v=xyz789",
            },
        ]

        results = transform_watch_history_items(items, "account1")

        assert len(results) == 2
        assert all(result is not None for result in results)
        assert results[0]["video_id"] == "abc123"
        assert results[1]["video_id"] == "xyz789"
        assert all(result["account_id"] == "account1" for result in results)

    def test_transform_watch_history_items_filters_invalid(self):
        """無効なアイテムをフィルタリングすること。"""
        watched_at = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)

        items = [
            {
                "video_id": "abc123",
                "title": "Valid Video",
                "channel_name": "Channel",
                "watched_at": watched_at,
                "video_url": "https://www.youtube.com/watch?v=abc123",
            },
            {
                # Missing channel_name
                "video_id": "invalid",
                "title": "Invalid Video",
                "watched_at": watched_at,
                "video_url": "https://www.youtube.com/watch?v=invalid",
            },
            {
                "video_id": "xyz789",
                "title": "Another Valid Video",
                "channel_name": "Channel 2",
                "watched_at": watched_at,
                "video_url": "https://www.youtube.com/watch?v=xyz789",
            },
        ]

        results = transform_watch_history_items(items, "account1")

        assert len(results) == 2
        assert results[0]["video_id"] == "abc123"
        assert results[1]["video_id"] == "xyz789"

    def test_transform_watch_history_items_empty_list(self):
        """空リストの場合は空リストを返すこと。"""
        results = transform_watch_history_items([], "account1")

        assert results == []

    def test_transform_watch_history_items_all_invalid(self):
        """すべてのアイテムが無効な場合は空リストを返すこと。"""
        items = [
            {
                "video_id": "",
                "title": "Video",
                "channel_name": "Channel",
                # Missing watched_at
                "video_url": "https://www.youtube.com/watch?v=test",
            }
        ]

        results = transform_watch_history_items(items, "account1")

        assert results == []


class TestTransformVideoInfo:
    """transform_video_infoのテスト。"""

    def test_transform_video_info_success(self):
        """正常ケース: YouTube APIレスポンスを変換すること。"""
        video = {
            "id": "abc123",
            "snippet": {
                "title": "Test Video Title",
                "channelId": "channel456",
                "channelTitle": "Test Channel",
                "publishedAt": "2024-01-01T00:00:00Z",
                "description": "Test description",
                "categoryId": "10",
                "tags": ["tag1", "tag2"],
                "thumbnails": {
                    "default": {"url": "https://i.ytimg.com/vi/abc123/default.jpg"},
                    "medium": {"url": "https://i.ytimg.com/vi/abc123/mqdefault.jpg"},
                },
            },
            "contentDetails": {"duration": "PT5M30S"},  # 5分30秒
            "statistics": {
                "viewCount": "1000",
                "likeCount": "100",
                "commentCount": "10",
            },
        }

        result = transform_video_info(video)

        assert result is not None
        assert result["video_id"] == "abc123"
        assert result["title"] == "Test Video Title"
        assert result["channel_id"] == "channel456"
        assert result["channel_name"] == "Test Channel"
        assert result["duration_seconds"] == 330  # 5分30秒 = 330秒
        assert result["view_count"] == 1000
        assert result["like_count"] == 100
        assert result["comment_count"] == 10
        assert result["published_at"] == datetime(
            2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc
        )
        assert "ytimg.com" in result["thumbnail_url"]
        assert result["description"] == "Test description"
        assert result["category_id"] == "10"
        assert result["tags"] == ["tag1", "tag2"]
        assert isinstance(result["updated_at"], datetime)

    def test_transform_video_info_minimal(self):
        """最小限のフィールドのみの場合。"""
        video = {
            "id": "abc123",
            "snippet": {
                "title": "Test Video",
                "channelId": "channel456",
            },
        }

        result = transform_video_info(video)

        assert result["video_id"] == "abc123"
        assert result["title"] == "Test Video"
        assert result["channel_id"] == "channel456"
        assert result["duration_seconds"] is None
        assert result["view_count"] is None
        assert result["like_count"] is None
        assert result["comment_count"] is None

    def test_transform_video_info_duration_parsing(self):
        """durationのパースをテスト。"""
        test_cases = [
            ("PT5S", 5),  # 5秒
            ("PT1M", 60),  # 1分
            ("PT1H", 3600),  # 1時間
            ("PT1H30M", 5400),  # 1時間30分
            ("PT1H30M15S", 5415),  # 1時間30分15秒
            ("PT10M30S", 630),  # 10分30秒
        ]

        for duration_str, expected_seconds in test_cases:
            video = {
                "id": "test123",
                "snippet": {"title": "Test", "channelId": "channel"},
                "contentDetails": {"duration": duration_str},
            }
            result = transform_video_info(video)
            assert result["duration_seconds"] == expected_seconds

    def test_transform_video_info_thumbnail_priority(self):
        """サムネイルURLの優先順位をテスト（high > medium > default）。"""
        video = {
            "id": "abc123",
            "snippet": {
                "title": "Test",
                "channelId": "channel",
                "thumbnails": {
                    "default": {"url": "https://default.jpg"},
                    "medium": {"url": "https://medium.jpg"},
                    "high": {"url": "https://high.jpg"},
                },
            },
        }

        result = transform_video_info(video)

        assert result["thumbnail_url"] == "https://high.jpg"

    def test_transform_video_info_no_thumbnails(self):
        """サムネイルがない場合はNoneを返すこと。"""
        video = {
            "id": "abc123",
            "snippet": {
                "title": "Test",
                "channelId": "channel",
            },
        }

        result = transform_video_info(video)

        assert result["thumbnail_url"] is None

    def test_transform_video_info_empty_statistics(self):
        """統計情報がない場合のデフォルト値。"""
        video = {
            "id": "abc123",
            "snippet": {
                "title": "Test",
                "channelId": "channel",
            },
            "statistics": {},
        }

        result = transform_video_info(video)

        assert result["view_count"] is None
        assert result["like_count"] is None
        assert result["comment_count"] is None


class TestTransformChannelInfo:
    """transform_channel_infoのテスト。"""

    def test_transform_channel_info_success(self):
        """正常ケース: YouTube APIレスポンスを変換すること。"""
        channel = {
            "id": "channel123",
            "snippet": {
                "title": "Test Channel",
                "description": "Channel description",
                "publishedAt": "2020-01-01T00:00:00Z",
                "country": "US",
                "thumbnails": {
                    "default": {"url": "https://yt3.ggpht.com/channel/default.jpg"}
                },
            },
            "statistics": {
                "subscriberCount": "10000",
                "videoCount": "500",
                "viewCount": "1000000",
            },
        }

        result = transform_channel_info(channel)

        assert result is not None
        assert result["channel_id"] == "channel123"
        assert result["channel_name"] == "Test Channel"
        assert result["subscriber_count"] == 10000
        assert result["video_count"] == 500
        assert result["view_count"] == 1000000
        assert result["published_at"] == datetime(
            2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc
        )
        assert "yt3.ggpht.com" in result["thumbnail_url"]
        assert result["description"] == "Channel description"
        assert result["country"] == "US"
        assert isinstance(result["updated_at"], datetime)

    def test_transform_channel_info_minimal(self):
        """最小限のフィールドのみの場合。"""
        channel = {
            "id": "channel123",
            "snippet": {
                "title": "Test Channel",
            },
        }

        result = transform_channel_info(channel)

        assert result["channel_id"] == "channel123"
        assert result["channel_name"] == "Test Channel"
        assert result["subscriber_count"] is None
        assert result["video_count"] is None
        assert result["view_count"] is None
        assert result["published_at"] is None
        assert result["thumbnail_url"] is None
        assert result["description"] is None
        assert result["country"] is None

    def test_transform_channel_info_empty_statistics(self):
        """統計情報がない場合のデフォルト値。"""
        channel = {
            "id": "channel123",
            "snippet": {
                "title": "Test Channel",
            },
            "statistics": {},
        }

        result = transform_channel_info(channel)

        assert result["subscriber_count"] is None
        assert result["video_count"] is None
        assert result["view_count"] is None

    def test_transform_channel_info_thumbnail_priority(self):
        """サムネイルURLの優先順位をテスト。"""
        channel = {
            "id": "channel123",
            "snippet": {
                "title": "Test Channel",
                "thumbnails": {
                    "default": {"url": "https://default.jpg"},
                    "medium": {"url": "https://medium.jpg"},
                    "high": {"url": "https://high.jpg"},
                },
            },
        }

        result = transform_channel_info(channel)

        assert result["thumbnail_url"] == "https://high.jpg"

    def test_transform_channel_info_no_thumbnails(self):
        """サムネイルがない場合はNoneを返すこと。"""
        channel = {
            "id": "channel123",
            "snippet": {
                "title": "Test Channel",
            },
        }

        result = transform_channel_info(channel)

        assert result["thumbnail_url"] is None
