"""YouTube Repository層のテスト。"""

from datetime import date

from pydantic import SecretStr

from backend.config import R2Config
from backend.infrastructure.repositories.youtube_repository import YouTubeRepository
from backend.tests.fixtures.youtube import patch_youtube_paths


def _mock_r2_config():
    """モックR2設定。"""
    return R2Config.model_construct(
        endpoint_url="https://test.r2.cloudflarestorage.com",
        access_key_id="test_key",
        secret_access_key=SecretStr("test_secret"),
        bucket_name="test-bucket",
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
    )


class TestYouTubeRepository:
    """YouTubeRepositoryのテスト。"""

    def test_get_watch_events(self, youtube_with_sample_data):
        """視聴イベントを取得。"""
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            repo = YouTubeRepository(_mock_r2_config())
            result = repo.get_watch_events(
                youtube_with_sample_data, date(2024, 1, 1), date(2024, 1, 3)
            )

        # Assert
        assert len(result) > 0
        assert "watch_event_id" in result[0]
        assert "video_title" in result[0]

    def test_get_watching_stats(self, youtube_with_sample_data):
        """視聴統計を取得。"""
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            repo = YouTubeRepository(_mock_r2_config())
            result = repo.get_watching_stats(
                youtube_with_sample_data,
                date(2024, 1, 1),
                date(2024, 1, 3),
                granularity="day",
            )

        # Assert
        assert len(result) > 0
        assert "period" in result[0]
        assert "watch_event_count" in result[0]
        assert "unique_video_count" in result[0]

    def test_get_top_videos(self, youtube_with_sample_data):
        """トップ動画を取得。"""
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            repo = YouTubeRepository(_mock_r2_config())
            result = repo.get_top_videos(
                youtube_with_sample_data, date(2024, 1, 1), date(2024, 1, 3)
            )

        # Assert
        assert len(result) > 0
        assert "video_id" in result[0]
        assert "watch_event_count" in result[0]

    def test_get_top_channels(self, youtube_with_sample_data):
        """トップチャンネルを取得。"""
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            repo = YouTubeRepository(_mock_r2_config())
            result = repo.get_top_channels(
                youtube_with_sample_data, date(2024, 1, 1), date(2024, 1, 3)
            )

        # Assert
        assert len(result) > 0
        assert "channel_id" in result[0]
        assert "channel_name" in result[0]
        assert "watch_event_count" in result[0]
        assert "unique_video_count" in result[0]

    def test_repository_has_four_canonical_methods(self):
        """リポジトリが4つの正規メソッドを持つ。"""
        # Arrange
        repo = YouTubeRepository(_mock_r2_config())

        # Assert
        assert hasattr(repo, "get_watch_events")
        assert hasattr(repo, "get_watching_stats")
        assert hasattr(repo, "get_top_videos")
        assert hasattr(repo, "get_top_channels")
        assert callable(repo.get_watch_events)
        assert callable(repo.get_watching_stats)
        assert callable(repo.get_top_videos)
        assert callable(repo.get_top_channels)
