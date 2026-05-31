"""Tools/YouTube/Stats層のテスト。"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from backend.domain.tools.youtube.stats import (
    GetYouTubeTopChannelsTool,
    GetYouTubeTopVideosTool,
    GetYouTubeWatchEventsTool,
    GetYouTubeWatchingStatsTool,
)


def _mock_conn_ctx():
    """DuckDBConnection のコンテキストマネージャーモックを返す。"""
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx


class TestGetYouTubeWatchEventsTool:
    """GetYouTubeWatchEventsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)
        assert tool.name == "get_youtube_watch_events"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        schema = tool.input_schema

        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        schema = tool.to_schema()

        assert schema.name == "get_youtube_watch_events"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_with_valid_dates(self, MockConn):
        """正しい日付でexecute()を実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_watch_events.return_value = [
            {
                "watch_event_id": "we_1",
                "watched_at": "2024-01-01T12:00:00Z",
                "video_id": "video_1",
                "video_title": "Video A",
                "channel_name": "Channel X",
                "content_type": "video",
            }
        ]
        tool = GetYouTubeWatchEventsTool(mock_repository)

        result = tool.execute(start_date="2024-01-01", end_date="2024-01-31", limit=10)

        assert len(result) == 1
        assert result[0]["watch_event_id"] == "we_1"
        mock_repository.get_watch_events.assert_called_once()
        call_args = mock_repository.get_watch_events.call_args
        assert call_args[0][0] is MockConn.return_value.__enter__.return_value  # conn
        assert call_args[0][1] == date(2024, 1, 1)  # start_date
        assert call_args[0][2] == date(2024, 1, 31)  # end_date
        assert call_args[0][3] == 10  # limit

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchEventsTool(mock_repository)

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_without_limit(self, MockConn):
        """limitなしで実行（全件取得）。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_watch_events.return_value = []
        tool = GetYouTubeWatchEventsTool(mock_repository)

        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        call_args = mock_repository.get_watch_events.call_args
        assert call_args[0][3] is None  # limit


class TestGetYouTubeWatchingStatsTool:
    """GetYouTubeWatchingStatsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)
        assert tool.name == "get_youtube_watching_stats"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        schema = tool.input_schema

        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "granularity" in schema["properties"]
        assert schema["properties"]["granularity"]["enum"] == ["day", "week", "month"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        schema = tool.to_schema()

        assert schema.name == "get_youtube_watching_stats"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_with_valid_parameters(self, MockConn):
        """正しいパラメータでexecute()を実行。"""
        MockConn.return_value = _mock_conn_ctx()

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

        result = tool.execute(
            start_date="2024-01-01", end_date="2024-01-31", granularity="day"
        )

        assert len(result) == 1
        assert result[0]["period"] == "2024-01-01"
        mock_repository.get_watching_stats.assert_called_once()
        call_args = mock_repository.get_watching_stats.call_args
        assert call_args[0][3] == "day"  # granularity

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(
                start_date="invalid-date", end_date="2024-01-31", granularity="day"
            )

    def test_execute_with_invalid_granularity_raises_error(self):
        """不正なgranularityでエラー。"""
        mock_repository = MagicMock()
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        with pytest.raises(ValueError, match="invalid_granularity"):
            tool.execute(
                start_date="2024-01-01", end_date="2024-01-31", granularity="invalid"
            )

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_with_default_granularity(self, MockConn):
        """granularityのデフォルト値で実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_watching_stats.return_value = []
        tool = GetYouTubeWatchingStatsTool(mock_repository)

        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        call_args = mock_repository.get_watching_stats.call_args
        assert call_args[0][3] == "day"  # granularity


class TestGetYouTubeTopVideosTool:
    """GetYouTubeTopVideosToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)
        assert tool.name == "get_youtube_top_videos"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        schema = tool.input_schema

        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        schema = tool.to_schema()

        assert schema.name == "get_youtube_top_videos"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_with_valid_dates(self, MockConn):
        """正しい日付でexecute()を実行。"""
        MockConn.return_value = _mock_conn_ctx()

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

        result = tool.execute(start_date="2024-01-01", end_date="2024-01-31", limit=10)

        assert len(result) == 1
        assert result[0]["video_id"] == "video_1"
        mock_repository.get_top_videos.assert_called_once()
        call_args = mock_repository.get_top_videos.call_args
        assert call_args[0][3] == 10  # limit

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopVideosTool(mock_repository)

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_with_default_limit(self, MockConn):
        """limitのデフォルト値で実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_top_videos.return_value = []
        tool = GetYouTubeTopVideosTool(mock_repository)

        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        call_args = mock_repository.get_top_videos.call_args
        assert call_args[0][3] == 10


class TestGetYouTubeTopChannelsTool:
    """GetYouTubeTopChannelsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)
        assert tool.name == "get_youtube_top_channels"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        schema = tool.input_schema

        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        schema = tool.to_schema()

        assert schema.name == "get_youtube_top_channels"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_with_valid_dates(self, MockConn):
        """正しい日付でexecute()を実行。"""
        MockConn.return_value = _mock_conn_ctx()

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

        result = tool.execute(start_date="2024-01-01", end_date="2024-01-31", limit=10)

        assert len(result) == 1
        assert result[0]["channel_name"] == "Channel A"
        mock_repository.get_top_channels.assert_called_once()
        call_args = mock_repository.get_top_channels.call_args
        assert call_args[0][3] == 10  # limit

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        mock_repository = MagicMock()
        tool = GetYouTubeTopChannelsTool(mock_repository)

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")

    @patch("backend.domain.tools.youtube.stats.DuckDBConnection")
    def test_execute_with_default_limit(self, MockConn):
        """limitのデフォルト値で実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_top_channels.return_value = []
        tool = GetYouTubeTopChannelsTool(mock_repository)

        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        call_args = mock_repository.get_top_channels.call_args
        assert call_args[0][3] == 10
