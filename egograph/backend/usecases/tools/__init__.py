"""Backend tools layer.

MCP風のツール設計を採用し、LLMエージェントがDuckDBデータに
アクセスできるようにします。
"""

from backend.domain.models.tool import Tool, ToolBase
from backend.domain.tools.spotify.stats import GetListeningStatsTool, GetTopTracksTool
from backend.domain.tools.youtube.stats import (
    GetYouTubeTopChannelsTool,
    GetYouTubeTopVideosTool,
    GetYouTubeWatchEventsTool,
    GetYouTubeWatchingStatsTool,
)
from backend.usecases.tools.factory import build_tool_registry
from backend.usecases.tools.registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolBase",
    "ToolRegistry",
    "build_tool_registry",
    "GetTopTracksTool",
    "GetListeningStatsTool",
    "GetYouTubeWatchEventsTool",
    "GetYouTubeWatchingStatsTool",
    "GetYouTubeTopVideosTool",
    "GetYouTubeTopChannelsTool",
]
