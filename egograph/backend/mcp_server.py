"""EgoGraph MCP Server エントリーポイント。"""

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool

from backend.config import BackendConfig
from backend.usecases.tools.factory import build_tool_registry

logger = logging.getLogger(__name__)


def create_mcp_server(config: BackendConfig) -> FastMCP:
    """既存ツールをMCPツールとして公開するFastMCPサーバーを作成する。

    Args:
        config: Backend設定

    Returns:
        設定済みのFastMCPインスタンス
    """
    mcp = FastMCP(
        "EgoGraph",
        instructions=(
            "Personal data warehouse. Access Spotify, GitHub, browser history "
            "data via tools. Use data_query for raw SQL queries (SELECT only)."
        ),
        streamable_http_path="/",
        transport_security=config.mcp_transport_security,
    )

    registry = build_tool_registry(config.r2)

    server = mcp._mcp_server

    @server.list_tools()
    async def handle_list_tools() -> list[Any]:
        """MCPツール一覧を返す。"""
        return [
            MCPTool(
                name=schema.name,
                description=schema.description,
                inputSchema=schema.inputSchema,
            )
            for schema in registry.get_all_schemas()
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> Any:
        """指定されたMCPツールを実行する。"""
        try:
            tool = registry.get_tool(name)
        except KeyError as exc:
            logger.warning("Unknown MCP tool requested: %s", name)
            raise ValueError(f"Unknown tool: {name}") from exc

        try:
            result = tool.execute(**arguments)
        except Exception as exc:
            logger.exception("MCP tool execution failed: %s", name)
            raise RuntimeError(f"Tool execution failed: {exc}") from exc

        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, default=str),
                )
            ],
            isError=False,
        )

    return mcp
