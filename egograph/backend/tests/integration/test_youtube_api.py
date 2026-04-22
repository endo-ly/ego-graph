"""YouTube API統合テスト。"""

import asyncio
import json
from unittest.mock import MagicMock, patch

from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from backend.domain.tools.youtube.stats import (
    GetYouTubeTopChannelsTool,
    GetYouTubeTopVideosTool,
    GetYouTubeWatchEventsTool,
    GetYouTubeWatchingStatsTool,
)
from backend.infrastructure.repositories import YouTubeRepository
from backend.mcp_server import create_mcp_server

# ========================================
# テスト1: watch-events API
# ========================================


class TestWatchEventsEndpoint:
    """GET /v1/data/youtube/watch-events エンドポイントのテスト。"""

    def test_youtube_watch_events_api_returns_expected_fields(
        self, test_client, mock_db_and_parquet
    ):
        """watch-events APIが期待するフィールドを返す。"""
        # Arrange: モックデータを準備
        mock_result = [
            {
                "watch_event_id": "we_1",
                "watched_at_utc": "2024-01-01T12:00:00Z",
                "video_id": "video_1",
                "video_url": "https://youtube.com/watch?v=video_1",
                "video_title": "Video A",
                "channel_id": "channel_1",
                "channel_name": "Channel X",
                "content_type": "video",
            }
        ]

        with patch(
            "backend.api.youtube.YouTubeRepository.get_watch_events",
            return_value=mock_result,
        ):
            # Act: APIリクエストを実行
            response = test_client.get(
                "/v1/data/youtube/watch-events?start_date=2024-01-01&end_date=2024-01-31",
                headers={"X-API-Key": "test-backend-key"},
            )

        # Assert: レスポンスのフィールドを検証
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert "watch_event_id" in item
        assert "watched_at_utc" in item
        assert "video_id" in item
        assert "video_url" in item
        assert "video_title" in item
        assert "channel_id" in item
        assert "channel_name" in item
        assert "content_type" in item


# ========================================
# テスト2: watching stats API
# ========================================


class TestWatchingStatsEndpoint:
    """GET /v1/data/youtube/stats/watching エンドポイントのテスト。"""

    def test_youtube_watching_stats_api_returns_unique_counts(
        self, test_client, mock_db_and_parquet
    ):
        """watching stats APIがユニークカウントを返す。"""
        # Arrange: モックデータを準備
        mock_result = [
            {
                "period": "2024-01-01",
                "watch_event_count": 20,
                "unique_video_count": 15,
                "unique_channel_count": 10,
            }
        ]

        with patch(
            "backend.api.youtube.YouTubeRepository.get_watching_stats",
            return_value=mock_result,
        ):
            # Act: APIリクエストを実行
            response = test_client.get(
                "/v1/data/youtube/stats/watching?start_date=2024-01-01&end_date=2024-01-31",
                headers={"X-API-Key": "test-backend-key"},
            )

        # Assert: レスポンスのフィールドを検証
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert "watch_event_count" in item
        assert "unique_video_count" in item
        assert "unique_channel_count" in item


# ========================================
# テスト3: top-videos API
# ========================================


class TestTopVideosEndpoint:
    """GET /v1/data/youtube/stats/top-videos エンドポイントのテスト。"""

    def test_youtube_top_videos_api_returns_video_ranking(
        self, test_client, mock_db_and_parquet
    ):
        """top-videos APIが動画ランキングを返す。"""
        # Arrange: watch_event_count降順のモックデータを準備
        mock_result = [
            {
                "video_id": "video_1",
                "video_title": "Video A",
                "channel_id": "channel_1",
                "channel_name": "Channel X",
                "watch_event_count": 30,
            },
            {
                "video_id": "video_2",
                "video_title": "Video B",
                "channel_id": "channel_2",
                "channel_name": "Channel Y",
                "watch_event_count": 15,
            },
        ]

        with patch(
            "backend.api.youtube.YouTubeRepository.get_top_videos",
            return_value=mock_result,
        ):
            # Act: APIリクエストを実行
            response = test_client.get(
                "/v1/data/youtube/stats/top-videos?start_date=2024-01-01&end_date=2024-01-31&limit=10",
                headers={"X-API-Key": "test-backend-key"},
            )

        # Assert: レスポンスのフィールドとランキング順を検証
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["watch_event_count"] >= data[1]["watch_event_count"]
        assert "video_id" in data[0]
        assert "video_title" in data[0]
        assert "watch_event_count" in data[0]


# ========================================
# テスト4: top-channels API
# ========================================


class TestTopChannelsEndpoint:
    """GET /v1/data/youtube/stats/top-channels エンドポイントのテスト。"""

    def test_youtube_top_channels_api_returns_channel_ranking(
        self, test_client, mock_db_and_parquet
    ):
        """top-channels APIがチャンネルランキングを返す。"""
        # Arrange: watch_event_count降順のモックデータを準備
        mock_result = [
            {
                "channel_id": "channel_1",
                "channel_name": "Channel X",
                "watch_event_count": 50,
                "unique_video_count": 10,
            },
            {
                "channel_id": "channel_2",
                "channel_name": "Channel Y",
                "watch_event_count": 25,
                "unique_video_count": 5,
            },
        ]

        with patch(
            "backend.api.youtube.YouTubeRepository.get_top_channels",
            return_value=mock_result,
        ):
            # Act: APIリクエストを実行
            response = test_client.get(
                "/v1/data/youtube/stats/top-channels?start_date=2024-01-01&end_date=2024-01-31&limit=10",
                headers={"X-API-Key": "test-backend-key"},
            )

        # Assert: レスポンスのフィールドとランキング順を検証
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["watch_event_count"] >= data[1]["watch_event_count"]
        assert "channel_id" in data[0]
        assert "channel_name" in data[0]
        assert "watch_event_count" in data[0]


# ========================================
# テスト5: MCP registry にYouTube toolsが含まれる
# ========================================


class TestMCPRegistryYouTubeTools:
    """MCPレジストリにYouTubeツールが含まれることのテスト。"""

    def test_mcp_registry_includes_youtube_tools(self, mock_backend_config):
        """MCP list_toolsに4つのYouTubeツールが含まれる。"""
        # Arrange: 実際のbuild_tool_registryを使ってMCPサーバーを構築
        # mock_backend_configはr2_configを持つため、YouTubeツールも登録される

        server = create_mcp_server(mock_backend_config)
        handler = server._mcp_server.request_handlers[ListToolsRequest]
        result = asyncio.run(handler(ListToolsRequest(method="tools/list"))).root

        # Act: ツール名一覧を取得
        tool_names = [tool.name for tool in result.tools]

        # Assert: 4つのYouTubeツールが含まれることを検証
        assert "get_youtube_watch_events" in tool_names
        assert "get_youtube_watching_stats" in tool_names
        assert "get_youtube_top_videos" in tool_names
        assert "get_youtube_top_channels" in tool_names


# ========================================
# テスト6: MCP call_tool がJSON payloadを返す
# ========================================


class TestMCPCallYouTubeTool:
    """MCP call_toolでYouTubeツールを実行するテスト。"""

    def test_mcp_call_youtube_tool_returns_json_payload(self, mock_backend_config):
        """MCP call_toolでYouTubeツールがJSONテキストを返す。"""
        # Arrange

        mock_result = [
            {
                "watch_event_id": "we_1",
                "watched_at_utc": "2024-01-01T12:00:00Z",
                "video_id": "video_1",
                "video_title": "Video A",
                "content_type": "video",
            }
        ]

        with patch.object(
            YouTubeRepository, "get_watch_events", return_value=mock_result
        ):
            server = create_mcp_server(mock_backend_config)
            handler = server._mcp_server.request_handlers[CallToolRequest]
            request = CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(
                    name="get_youtube_watch_events",
                    arguments={
                        "start_date": "2024-01-01",
                        "end_date": "2024-01-31",
                    },
                ),
            )

            # Act: call_toolを実行
            result = asyncio.run(handler(request)).root

        # Assert: JSONテキストが返ることを検証
        assert result.isError is False
        assert result.content[0].type == "text"
        payload = json.loads(result.content[0].text)
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["watch_event_id"] == "we_1"


# ========================================
# テスト7: input_schemaがドキュメント仕様に一致
# ========================================


class TestToolInputSchemaContract:
    """ツールのinput_schemaがドキュメント仕様に一致するテスト。"""

    def test_tool_input_schema_matches_documented_contract(self):
        """各YouTubeツールのinput_schemaが仕様通りの必須フィールドを持つ。"""
        # Arrange: ツールインスタンスを生成

        mock_repo = MagicMock()

        tools = [
            GetYouTubeWatchEventsTool(mock_repo),
            GetYouTubeWatchingStatsTool(mock_repo),
            GetYouTubeTopVideosTool(mock_repo),
            GetYouTubeTopChannelsTool(mock_repo),
        ]

        # Act & Assert: 各ツールのスキーマを検証
        for tool in tools:
            schema = tool.input_schema
            # 必須フィールド
            assert schema["type"] == "object"
            assert "start_date" in schema["properties"]
            assert "end_date" in schema["properties"]
            assert "start_date" in schema["required"]
            assert "end_date" in schema["required"]

            # ツール名が get_youtube_ プレフィックスを持つ
            assert tool.name.startswith("get_youtube_")
