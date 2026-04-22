"""Tools/YouTube/Stats層のテスト。"""

from unittest.mock import MagicMock

import pytest
from backend.domain.tools.youtube.stats import (
    GetYouTubeTopChannelsTool,
    GetYouTubeTopVideosTool,
    GetYouTubeWatchEventsTool,
    GetYouTubeWatchingStatsTool,
)


class TestGetYouTubeWatchEventsTool:
    """GetYouTubeWatchEventsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        # Assert
        assert tool.name == "get_youtube_watch_events"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        # Assert
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        # Act
        schema = tool.input_schema

        # Assert
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        # Act
        schema = tool.to_schema()

        # Assert
        assert schema.name == "get_youtube_watch_events"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    def test_execute_with_valid_dates(self):
        """正しい日付でexecute()を実行。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_watch_events.return_value = [
            {
                "watch_event_id": "we_1",
                "watched_at_utc": "2024-01-01T12:00:00Z",
                "video_id": "video_1",
                "video_title": "Video A",
                "channel_name": "Channel X",
                "content_type": "video",
            }
        ]
        tool = GetYouTubeWatchEventsTool(mock_repository)

        # Act
        result = tool.execute(start_date="2024-01-01", end_date="2024-01-31", limit=10)

        # Assert
        assert len(result) == 1
        assert result[0]["watch_event_id"] == "we_1"
        mock_repository.get_watch_events.assert_called_once()
        call_args = mock_repository.get_watch_events.call_args
        assert call_args[0][2] == 10  # limit

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        # Act & Assert
        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")

    def test_execute_without_limit(self):
        """limitなしで実行（全件取得）。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_watch_events.return_value = []
        tool = GetYouTubeWatchEventsTool(mock_repository)

        # Act
        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        # Assert
        call_args = mock_repository.get_watch_events.call_args
        assert call_args[0][2] is None


class TestGetYouTubeWatchingStatsTool:
    """GetYouTubeWatchingStatsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Assert
        assert tool.name == "get_youtube_watching_stats"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Assert
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Act
        schema = tool.input_schema

        # Assert
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "granularity" in schema["properties"]
        assert schema["properties"]["granularity"]["enum"] == ["day", "week", "month"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Act
        schema = tool.to_schema()

        # Assert
        assert schema.name == "get_youtube_watching_stats"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    def test_execute_with_valid_parameters(self):
        """正しいパラメータでexecute()を実行。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_watching_stats.return_value = [
            {
                "period": "2024-01-01",
                "watch_event_count": 20,
                "unique_video_count": 15,
                "unique_channel_count": 10,
            }
        ]
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Act
        result = tool.execute(
            start_date="2024-01-01", end_date="2024-01-31", granularity="day"
        )

        # Assert
        assert len(result) == 1
        assert result[0]["period"] == "2024-01-01"
        mock_repository.get_watching_stats.assert_called_once()
        call_args = mock_repository.get_watching_stats.call_args
        assert call_args[0][2] == "day"

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Act & Assert
        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(
                start_date="invalid-date", end_date="2024-01-31", granularity="day"
            )

    def test_execute_with_invalid_granularity_raises_error(self):
        """不正なgranularityでエラー。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Act & Assert
        with pytest.raises(ValueError, match="invalid_granularity"):
            tool.execute(
                start_date="2024-01-01", end_date="2024-01-31", granularity="invalid"
            )

    def test_execute_with_default_granularity(self):
        """granularityのデフォルト値で実行。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_watching_stats.return_value = []
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        # Act
        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        # Assert
        call_args = mock_repository.get_watching_stats.call_args
        assert call_args[0][2] == "day"


class TestGetYouTubeTopVideosTool:
    """GetYouTubeTopVideosToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        # Assert
        assert tool.name == "get_youtube_top_videos"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        # Assert
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        # Act
        schema = tool.input_schema

        # Assert
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        # Act
        schema = tool.to_schema()

        # Assert
        assert schema.name == "get_youtube_top_videos"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    def test_execute_with_valid_dates(self):
        """正しい日付でexecute()を実行。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_top_videos.return_value = [
            {
                "video_id": "video_1",
                "video_title": "Video A",
                "channel_name": "Channel X",
                "watch_event_count": 10,
            }
        ]
        tool = GetYouTubeTopVideosTool(mock_repository)

        # Act
        result = tool.execute(start_date="2024-01-01", end_date="2024-01-31", limit=10)

        # Assert
        assert len(result) == 1
        assert result[0]["video_id"] == "video_1"
        mock_repository.get_top_videos.assert_called_once()
        call_args = mock_repository.get_top_videos.call_args
        assert call_args[0][2] == 10

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        # Act & Assert
        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")

    def test_execute_with_default_limit(self):
        """limitのデフォルト値で実行。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_top_videos.return_value = []
        tool = GetYouTubeTopVideosTool(mock_repository)

        # Act
        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        # Assert
        call_args = mock_repository.get_top_videos.call_args
        assert call_args[0][2] == 10


class TestGetYouTubeTopChannelsTool:
    """GetYouTubeTopChannelsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        # Assert
        assert tool.name == "get_youtube_top_channels"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        # Assert
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        # Act
        schema = tool.input_schema

        # Assert
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        # Act
        schema = tool.to_schema()

        # Assert
        assert schema.name == "get_youtube_top_channels"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    def test_execute_with_valid_dates(self):
        """正しい日付でexecute()を実行。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_top_channels.return_value = [
            {
                "channel_name": "Channel A",
                "channel_id": "channel_a_id",
                "watch_event_count": 10,
                "unique_video_count": 5,
            }
        ]
        tool = GetYouTubeTopChannelsTool(mock_repository)

        # Act
        result = tool.execute(start_date="2024-01-01", end_date="2024-01-31", limit=10)

        # Assert
        assert len(result) == 1
        assert result[0]["channel_name"] == "Channel A"
        mock_repository.get_top_channels.assert_called_once()
        call_args = mock_repository.get_top_channels.call_args
        assert call_args[0][2] == 10

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        # Arrange
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        # Act & Assert
        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")

    def test_execute_with_default_limit(self):
        """limitのデフォルト値で実行。"""
        # Arrange
        mock_repository = MagicMock()
        mock_repository.get_top_channels.return_value = []
        tool = GetYouTubeTopChannelsTool(mock_repository)

        # Act
        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        # Assert
        call_args = mock_repository.get_top_channels.call_args
        assert call_args[0][2] == 10
