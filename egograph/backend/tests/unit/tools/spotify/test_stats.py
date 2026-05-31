"""Tools/Spotify/Stats層のテスト。"""

from unittest.mock import MagicMock, patch

import pytest

from backend.domain.tools.spotify.stats import GetListeningStatsTool, GetTopTracksTool


def _mock_conn_ctx():
    """DuckDBConnection のコンテキストマネージャーモックを返す。"""
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx


class TestGetTopTracksTool:
    """GetTopTracksToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetTopTracksTool(mock_repository)
        assert tool.name == "get_top_tracks"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetTopTracksTool(mock_repository)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        mock_repository = MagicMock()
        tool = GetTopTracksTool(mock_repository)

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
        tool = GetTopTracksTool(mock_repository)

        schema = tool.to_schema()

        assert schema.name == "get_top_tracks"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    @patch("backend.domain.tools.spotify.stats.DuckDBConnection")
    def test_execute_with_valid_dates(self, MockConn):
        """正しい日付でexecute()を実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_top_tracks.return_value = [
            {
                "track_name": "Song A",
                "artist": "Artist X",
                "play_count": 10,
                "total_minutes": 30.0,
                "played_at_utc": [
                    "2024-01-01T10:00:00",
                    "2024-01-02T14:00:00",
                ],
            }
        ]
        tool = GetTopTracksTool(mock_repository)

        result = tool.execute(start_date="2024-01-01", end_date="2024-01-31", limit=10)

        assert len(result) == 1
        assert result[0]["track_name"] == "Song A"
        mock_repository.get_top_tracks.assert_called_once()
        call_args = mock_repository.get_top_tracks.call_args
        # 引数: (conn, start_date, end_date, limit)
        assert call_args[0][3] == 10  # limit

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        mock_repository = MagicMock()
        tool = GetTopTracksTool(mock_repository)

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")

    @patch("backend.domain.tools.spotify.stats.DuckDBConnection")
    def test_execute_with_default_limit(self, MockConn):
        """limitのデフォルト値で実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_top_tracks.return_value = []
        tool = GetTopTracksTool(mock_repository)

        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        call_args = mock_repository.get_top_tracks.call_args
        assert call_args[0][3] == 10  # デフォルトlimit


class TestGetListeningStatsTool:
    """GetListeningStatsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetListeningStatsTool(mock_repository)
        assert tool.name == "get_listening_stats"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        mock_repository = MagicMock()
        tool = GetListeningStatsTool(mock_repository)
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        mock_repository = MagicMock()
        tool = GetListeningStatsTool(mock_repository)

        schema = tool.input_schema

        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "granularity" in schema["properties"]
        assert schema["properties"]["granularity"]["enum"] == ["day", "week", "month"]

    def test_to_schema_generates_tool(self):
        """to_schema()がToolスキーマを生成。"""
        mock_repository = MagicMock()
        tool = GetListeningStatsTool(mock_repository)

        schema = tool.to_schema()

        assert schema.name == "get_listening_stats"
        assert isinstance(schema.description, str)
        assert isinstance(schema.inputSchema, dict)

    @patch("backend.domain.tools.spotify.stats.DuckDBConnection")
    def test_execute_with_valid_parameters(self, MockConn):
        """正しいパラメータでexecute()を実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_listening_stats.return_value = [
            {
                "period": "2024-01-01",
                "total_ms": 3600000,
                "track_count": 20,
                "unique_tracks": 15,
            }
        ]
        tool = GetListeningStatsTool(mock_repository)

        result = tool.execute(
            start_date="2024-01-01", end_date="2024-01-31", granularity="day"
        )

        assert len(result) == 1
        assert result[0]["period"] == "2024-01-01"
        mock_repository.get_listening_stats.assert_called_once()
        call_args = mock_repository.get_listening_stats.call_args
        # 引数: (conn, start_date, end_date, granularity)
        assert call_args[0][3] == "day"  # granularity

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        mock_repository = MagicMock()
        tool = GetListeningStatsTool(mock_repository)

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(
                start_date="invalid-date", end_date="2024-01-31", granularity="day"
            )

    @patch("backend.domain.tools.spotify.stats.DuckDBConnection")
    def test_execute_with_default_granularity(self, MockConn):
        """granularityのデフォルト値で実行。"""
        MockConn.return_value = _mock_conn_ctx()

        mock_repository = MagicMock()
        mock_repository.get_listening_stats.return_value = []
        tool = GetListeningStatsTool(mock_repository)

        tool.execute(start_date="2024-01-01", end_date="2024-01-31")

        call_args = mock_repository.get_listening_stats.call_args
        assert call_args[0][3] == "day"  # デフォルトgranularity
