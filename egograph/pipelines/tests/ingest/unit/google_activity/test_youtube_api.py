"""YouTube Data API v3 クライアントのテスト。"""

from unittest.mock import Mock, patch

import pytest
import requests

from pipelines.sources.google_activity.youtube_api import (
    QuotaExceededError,
    YouTubeAPIClient,
)


@pytest.fixture
def mock_api_key():
    """テスト用のモック API キー。"""
    return "test_api_key_12345"


@pytest.fixture
def youtube_client(mock_api_key):
    """YouTubeAPIClient のインスタンス。"""
    return YouTubeAPIClient(api_key=mock_api_key)


@pytest.fixture
def mock_video_response():
    """YouTube API の動画レスポンスをモックする。"""
    return {
        "items": [
            {
                "id": "video1",
                "snippet": {"title": "Video 1", "channelId": "channel1"},
                "statistics": {"viewCount": "100", "likeCount": "10"},
            },
            {
                "id": "video2",
                "snippet": {"title": "Video 2", "channelId": "channel2"},
                "statistics": {"viewCount": "200", "likeCount": "20"},
            },
        ],
        "pageInfo": {"totalResults": 2, "resultsPerPage": 50},
    }


@pytest.fixture
def mock_channel_response():
    """YouTube API のチャンネルレスポンスをモックする。"""
    return {
        "items": [
            {
                "id": "channel1",
                "snippet": {"title": "Channel 1", "description": "Test channel 1"},
                "statistics": {
                    "subscriberCount": "1000",
                    "videoCount": "100",
                    "viewCount": "10000",
                },
            },
            {
                "id": "channel2",
                "snippet": {"title": "Channel 2", "description": "Test channel 2"},
                "statistics": {
                    "subscriberCount": "2000",
                    "videoCount": "200",
                    "viewCount": "20000",
                },
            },
        ],
        "pageInfo": {"totalResults": 2, "resultsPerPage": 50},
    }


@pytest.fixture
def mock_quota_exceeded_response():
    """クォータ超過エラーレスポンスをモックする。"""
    return {
        "error": {
            "code": 403,
            "message": (
                "The request cannot be completed because you have exceeded your quota."
            ),
            "errors": [
                {
                    "domain": "youtube.quota",
                    "reason": "quotaExceeded",
                    "message": (
                        "The request cannot be completed because you have "
                        "exceeded your quota."
                    ),
                }
            ],
        }
    }


class TestYouTubeAPIClientInit:
    """YouTubeAPIClient の初期化テスト。"""

    def test_init_with_api_key(self, mock_api_key):
        """API キーを使用してクライアントを初期化できること。"""
        # Act
        client = YouTubeAPIClient(api_key=mock_api_key)

        # Assert
        assert client.api_key == mock_api_key


class TestGetVideos:
    """get_videos メソッドのテスト。"""

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_videos_single_batch(
        self, mock_get, youtube_client, mock_video_response
    ):
        """1回のリクエストで全動画を取得できること（50件以下）。"""
        # Arrange
        video_ids = ["video1", "video2"]
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_video_response
        mock_get.return_value = mock_response

        # Act
        result = youtube_client.get_videos(video_ids)

        # Assert
        assert len(result) == 2
        assert result[0]["id"] == "video1"
        assert result[1]["id"] == "video2"
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[1]["params"]["id"] == "video1,video2"

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_videos_multiple_batches(
        self, mock_get, youtube_client, mock_video_response
    ):
        """複数のバッチに分けて動画を取得できること（50件超過）。"""
        # Arrange
        # 120件の動画IDを作成（3バッチ: 50 + 50 + 20）
        video_ids = [f"video{i}" for i in range(120)]

        # 各バッチのモックレスポンスを設定
        def mock_get_side_effect(*args, **kwargs):
            # params から video_ids を抽出して正しい数の結果を返す
            video_ids_param = kwargs["params"]["id"]
            num_items = len(video_ids_param.split(","))

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "items": [
                    {
                        "id": f"video{i}",
                        "snippet": {"title": f"Video {i}", "channelId": "channel1"},
                        "statistics": {"viewCount": str(i * 10), "likeCount": str(i)},
                    }
                    for i in range(num_items)
                ],
                "pageInfo": {"totalResults": num_items, "resultsPerPage": 50},
            }
            return mock_response

        mock_get.side_effect = mock_get_side_effect

        # Act
        result = youtube_client.get_videos(video_ids)

        # Assert
        assert len(result) == 120
        assert mock_get.call_count == 3  # 50 + 50 + 20 = 120

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_videos_empty_list(self, mock_get, youtube_client):
        """空のリストの場合、リクエストを行わず空リストを返すこと。"""
        # Act
        result = youtube_client.get_videos([])

        # Assert
        assert result == []
        mock_get.assert_not_called()

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_videos_quota_exceeded(
        self, mock_get, youtube_client, mock_quota_exceeded_response
    ):
        """クォータ超過時に QuotaExceededError をスローすること。"""
        # Arrange
        video_ids = ["video1", "video2"]
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = mock_quota_exceeded_response
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(QuotaExceededError) as exc_info:
            youtube_client.get_videos(video_ids)

        assert "quota" in str(exc_info.value).lower()

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_videos_http_error(self, mock_get, youtube_client):
        """HTTP エラー時に requests.HTTPError をスローすること。"""
        # Arrange
        video_ids = ["video1"]
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error"
        )
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(requests.HTTPError):
            youtube_client.get_videos(video_ids)


class TestGetChannels:
    """get_channels メソッドのテスト。"""

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_channels_single_batch(
        self, mock_get, youtube_client, mock_channel_response
    ):
        """1回のリクエストで全チャンネルを取得できること（50件以下）。"""
        # Arrange
        channel_ids = ["channel1", "channel2"]
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_channel_response
        mock_get.return_value = mock_response

        # Act
        result = youtube_client.get_channels(channel_ids)

        # Assert
        assert len(result) == 2
        assert result[0]["id"] == "channel1"
        assert result[1]["id"] == "channel2"
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[1]["params"]["id"] == "channel1,channel2"

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_channels_multiple_batches(
        self, mock_get, youtube_client, mock_channel_response
    ):
        """複数のバッチに分けてチャンネルを取得できること（50件超過）。"""
        # Arrange
        # 130件のチャンネルIDを作成（3バッチ: 50 + 50 + 30）
        channel_ids = [f"channel{i}" for i in range(130)]

        # 各バッチのモックレスポンスを設定
        def mock_get_side_effect(*args, **kwargs):
            # params から channel_ids を抽出して正しい数の結果を返す
            channel_ids_param = kwargs["params"]["id"]
            num_items = len(channel_ids_param.split(","))

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "items": [
                    {
                        "id": f"channel{i}",
                        "snippet": {
                            "title": f"Channel {i}",
                            "description": f"Test channel {i}",
                        },
                        "statistics": {
                            "subscriberCount": str(i * 100),
                            "videoCount": str(i * 10),
                            "viewCount": str(i * 1000),
                        },
                    }
                    for i in range(num_items)
                ],
                "pageInfo": {"totalResults": num_items, "resultsPerPage": 50},
            }
            return mock_response

        mock_get.side_effect = mock_get_side_effect

        # Act
        result = youtube_client.get_channels(channel_ids)

        # Assert
        assert len(result) == 130
        assert mock_get.call_count == 3  # 50 + 50 + 30 = 130

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_channels_empty_list(self, mock_get, youtube_client):
        """空のリストの場合、リクエストを行わず空リストを返すこと。"""
        # Act
        result = youtube_client.get_channels([])

        # Assert
        assert result == []
        mock_get.assert_not_called()

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_channels_quota_exceeded(
        self, mock_get, youtube_client, mock_quota_exceeded_response
    ):
        """クォータ超過時に QuotaExceededError をスローすること。"""
        # Arrange
        channel_ids = ["channel1", "channel2"]
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = mock_quota_exceeded_response
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(QuotaExceededError) as exc_info:
            youtube_client.get_channels(channel_ids)

        assert "quota" in str(exc_info.value).lower()

    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_channels_http_error(self, mock_get, youtube_client):
        """HTTP エラー時に requests.HTTPError をスローすること。"""
        # Arrange
        channel_ids = ["channel1"]
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error"
        )
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(requests.HTTPError):
            youtube_client.get_channels(channel_ids)


class TestRetryLogic:
    """再試行ロジックのテスト。"""

    @patch("pipelines.sources.google_activity.youtube_api.time.sleep")
    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_videos_retry_on_failure(
        self, mock_get, mock_sleep, youtube_client, mock_video_response
    ):
        """一時的な失敗時に再試行が行われること。"""
        # Arrange
        video_ids = ["video1"]

        # 最初の2回は失敗、3回目は成功
        mock_fail_response = Mock()
        mock_fail_response.status_code = 500
        mock_fail_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error"
        )

        mock_success_response = Mock()
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = mock_video_response

        mock_get.side_effect = [
            mock_fail_response,
            mock_fail_response,
            mock_success_response,
        ]

        # Act
        # デフォルトのMAX_RETRIES=3なので、2回失敗しても成功するはず
        result = youtube_client.get_videos(video_ids)

        # Assert
        # 3回リトライが行われたことを確認（2回失敗 + 1回成功）
        assert mock_get.call_count == 3
        # sleep が3回呼ばれたことを確認（2回リトライ + 1回レートリミット待機）
        assert mock_sleep.call_count == 3
        # 最終的に成功したことを確認
        assert len(result) == 2

    @patch("pipelines.sources.google_activity.youtube_api.time.sleep")
    @patch("pipelines.sources.google_activity.youtube_api.requests.get")
    def test_get_channels_retry_on_failure(
        self, mock_get, mock_sleep, youtube_client, mock_channel_response
    ):
        """一時的な失敗時に再試行が行われること（チャンネル）。"""
        # Arrange
        channel_ids = ["channel1"]

        # 最初の2回は失敗、3回目は成功
        mock_fail_response = Mock()
        mock_fail_response.status_code = 500
        mock_fail_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error"
        )

        mock_success_response = Mock()
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = mock_channel_response

        mock_get.side_effect = [
            mock_fail_response,
            mock_fail_response,
            mock_success_response,
        ]

        # Act
        result = youtube_client.get_channels(channel_ids)

        # Assert
        # 3回リトライが行われたことを確認（2回失敗 + 1回成功）
        assert mock_get.call_count == 3
        # sleep が3回呼ばれたことを確認（2回リトライ + 1回レートリミット待機）
        assert mock_sleep.call_count == 3
        # 最終的に成功したことを確認
        assert len(result) == 2
