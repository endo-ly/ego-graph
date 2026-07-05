"""MCP Server エントリーポイントのテスト。"""

import asyncio
import json
from typing import Any
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from backend.domain.models.tool import ToolBase
from backend.mcp_server import create_mcp_server
from backend.usecases.tools.registry import ToolRegistry


class MockTool(ToolBase):
    """テスト用の正常系ツール。"""

    def __init__(self, name: str, description: str, result: dict[str, object]):
        self._name = name
        self._description = description
        self._result = result
        self.calls: list[dict[str, object]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
        }

    def execute(self, **params) -> dict[str, object]:
        self.calls.append(params)
        return self._result


class ErrorTool(ToolBase):
    """テスト用の異常系ツール。"""

    @property
    def name(self) -> str:
        return "error_tool"

    @property
    def description(self) -> str:
        return "Always raises"

    @property
    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def execute(self, **params) -> dict[str, object]:
        raise RuntimeError("boom")


class R2ErrorTool(ToolBase):
    """R2 URL を含むエラーメッセージを出すツール。"""

    @property
    def name(self) -> str:
        return "r2_error_tool"

    @property
    def description(self) -> str:
        return "Raises with R2 URL"

    @property
    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def execute(self, **params) -> dict[str, object]:
        raise RuntimeError(
            "Connection refused: https://abc123.r2.cloudflarestorage.com/data"
        )


class S3ErrorTool(ToolBase):
    """s3:// パスを含むエラーメッセージを出すツール。"""

    @property
    def name(self) -> str:
        return "s3_error_tool"

    @property
    def description(self) -> str:
        return "Raises with s3 path"

    @property
    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    def execute(self, **params) -> dict[str, object]:
        raise RuntimeError("Failed to read s3://secret-bucket/events/spotify.parquet")


def _build_registry(*tools: Any) -> Any:
    """テスト用レジストリを構築する。"""
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def _run_list_tools(server: Any):
    """list_tools ハンドラを実行する。"""
    handler = server._mcp_server.request_handlers[ListToolsRequest]
    return asyncio.run(handler(ListToolsRequest(method="tools/list"))).root


def _run_call_tool(server: Any, name: str, arguments: dict[str, object]):
    """call_tool ハンドラを実行する。"""
    handler = server._mcp_server.request_handlers[CallToolRequest]
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    return asyncio.run(handler(request)).root


def test_create_mcp_server_returns_fastmcp(mock_backend_config):
    """FastMCP インスタンスを返す。"""
    # Arrange: 空のツールレジストリを準備
    registry = _build_registry()

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        # Act: MCPサーバーを生成
        server = create_mcp_server(mock_backend_config)

    # Assert: FastMCP インスタンスであることを検証
    assert isinstance(server, FastMCP)


def test_list_tools_returns_all_tools(mock_backend_config):
    """全ツールを返す。"""
    # Arrange: 2件のツールを持つレジストリを準備
    registry = _build_registry(
        MockTool("tool_a", "Tool A", {"result": 1}),
        MockTool("tool_b", "Tool B", {"result": 2}),
    )

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: list_tools ハンドラを実行
    result = _run_list_tools(server)

    # Assert: レジストリと同数のツールが返ることを検証
    assert len(result.tools) == 2


def test_list_tools_tool_names(mock_backend_config):
    """返却ツール名が期待通り。"""
    # Arrange: 名前の異なるツールを準備
    registry = _build_registry(
        MockTool("spotify_stats", "Spotify stats", {"result": 1}),
        MockTool("github_worklog", "GitHub worklog", {"result": 2}),
    )

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: list_tools の名前一覧を取得
    result = _run_list_tools(server)
    tool_names = [tool.name for tool in result.tools]

    # Assert: 期待したツール名が返ることを検証
    assert tool_names == ["spotify_stats", "github_worklog"]


def test_list_tools_has_json_schema(mock_backend_config):
    """各ツールが JSON Schema を持つ。"""
    # Arrange: スキーマ付きツールを準備
    registry = _build_registry(
        MockTool("tool_a", "Tool A", {"result": 1}),
        MockTool("tool_b", "Tool B", {"result": 2}),
    )

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: list_tools の結果を取得
    result = _run_list_tools(server)

    # Assert: 各ツールの inputSchema が dict かつ type を持つことを検証
    assert all(isinstance(tool.inputSchema, dict) for tool in result.tools)
    assert all("type" in tool.inputSchema for tool in result.tools)


def test_call_tool_returns_result(mock_backend_config):
    """call_tool が JSON テキスト結果を返す。"""
    # Arrange: 実行履歴を確認できるツールを準備
    tool = MockTool("tool_a", "Tool A", {"message": "ok", "count": 1})
    registry = _build_registry(tool)

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: call_tool ハンドラを実行
    result = _run_call_tool(server, "tool_a", {"value": 42})

    # Assert: ツール実行と JSON テキスト返却を検証
    assert tool.calls == [{"value": 42}]
    assert result.isError is False
    assert result.content[0].type == "text"
    assert json.loads(result.content[0].text) == {"message": "ok", "count": 1}


def test_call_tool_unknown_raises(mock_backend_config):
    """未知ツール呼び出しはエラー結果になる。"""
    # Arrange: 空のレジストリを準備
    registry = _build_registry()

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: 未知ツールを呼び出す
    result = _run_call_tool(server, "missing_tool", {})

    # Assert: エラー結果が返ることを検証
    assert result.isError is True
    assert result.content[0].text == "Unknown tool: missing_tool"


def test_call_tool_execution_error(mock_backend_config):
    """実行失敗時はエラー結果になる。"""
    # Arrange: 常に例外を送出するツールを準備
    registry = _build_registry(ErrorTool())

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: 失敗するツールを呼び出す
    result = _run_call_tool(server, "error_tool", {})

    # Assert: エラー結果が返ることを検証
    assert result.isError is True
    assert result.content[0].text == "Tool execution failed: boom"


def test_create_mcp_server_with_none_r2(mock_backend_config):
    """r2=None でも空サーバーを生成できる。"""
    # Arrange: r2 を無効化し、空のレジストリを準備
    mock_backend_config.r2 = None
    registry = _build_registry()

    with patch(
        "backend.mcp_server.build_tool_registry", return_value=registry
    ) as mock_build:
        # Act: MCPサーバーを生成して list_tools を実行
        server = create_mcp_server(mock_backend_config)
        result = _run_list_tools(server)

    # Assert: build_tool_registry が None で呼ばれ、ツール0件で返ることを検証
    mock_build.assert_called_once_with(
        None,
        tz=mock_backend_config.timezone,
        timezone_configured=mock_backend_config.timezone_configured,
    )
    assert isinstance(server, FastMCP)
    assert result.tools == []


def test_call_tool_error_excludes_r2_url(mock_backend_config):
    """ツール実行エラー時に R2 URL がレスポンスに含まれない。"""
    # Arrange: R2 URL を含むエラーを発生させるツールを準備
    registry = _build_registry(R2ErrorTool())

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: ツールを実行
    result = _run_call_tool(server, "r2_error_tool", {})

    # Assert: エラー結果に R2 URL が含まれないことを検証
    assert result.isError is True
    assert "r2.cloudflarestorage.com" not in result.content[0].text
    assert "abc123" not in result.content[0].text


def test_call_tool_error_excludes_s3_path(mock_backend_config):
    """ツール実行エラー時に s3:// パスがレスポンスに含まれない。"""
    # Arrange: s3:// パスを含むエラーを発生させるツールを準備
    registry = _build_registry(S3ErrorTool())

    with patch("backend.mcp_server.build_tool_registry", return_value=registry):
        server = create_mcp_server(mock_backend_config)

    # Act: ツールを実行
    result = _run_call_tool(server, "s3_error_tool", {})

    # Assert: エラー結果に s3:// が含まれないことを検証
    assert result.isError is True
    assert "s3://" not in result.content[0].text
    assert "secret-bucket" not in result.content[0].text
