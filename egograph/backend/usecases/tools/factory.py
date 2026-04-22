"""ツールレジストリの構築ヘルパー。"""

from backend.config import R2Config
from backend.domain.tools.browser_history.page_views import (
    GetPageViewsTool,
    GetTopDomainsTool,
)
from backend.domain.tools.data_query import DataQueryTool
from backend.domain.tools.github.worklog import (
    GetActivityStatsTool,
    GetCommitsTool,
    GetPullRequestsTool,
    GetRepositoriesTool,
    GetRepoSummaryStatsTool,
)
from backend.domain.tools.spotify.stats import GetListeningStatsTool, GetTopTracksTool
from backend.domain.tools.youtube.stats import (
    GetYouTubeTopChannelsTool,
    GetYouTubeTopVideosTool,
    GetYouTubeWatchEventsTool,
    GetYouTubeWatchingStatsTool,
)
from backend.infrastructure.repositories import (
    BrowserHistoryRepository,
    GitHubRepository,
    SpotifyRepository,
    YouTubeRepository,
)
from backend.usecases.tools.registry import ToolRegistry


def build_tool_registry(r2_config: R2Config | None) -> ToolRegistry:
    """R2設定に応じたツールレジストリを構築する。"""
    tool_registry = ToolRegistry()

    if not r2_config:
        return tool_registry

    # Spotifyツール
    spotify_repository = SpotifyRepository(r2_config)
    tool_registry.register(GetTopTracksTool(spotify_repository))
    tool_registry.register(GetListeningStatsTool(spotify_repository))

    browser_history_repository = BrowserHistoryRepository(r2_config)
    tool_registry.register(GetPageViewsTool(browser_history_repository))
    tool_registry.register(GetTopDomainsTool(browser_history_repository))

    # GitHubツール
    github_repository = GitHubRepository(r2_config)
    tool_registry.register(GetPullRequestsTool(github_repository))
    tool_registry.register(GetCommitsTool(github_repository))
    tool_registry.register(GetRepositoriesTool(github_repository))
    tool_registry.register(GetActivityStatsTool(github_repository))
    tool_registry.register(GetRepoSummaryStatsTool(github_repository))

    # Data Query ツール
    tool_registry.register(DataQueryTool(r2_config))

    # YouTubeツール
    youtube_repository = YouTubeRepository(r2_config)
    tool_registry.register(GetYouTubeWatchEventsTool(youtube_repository))
    tool_registry.register(GetYouTubeWatchingStatsTool(youtube_repository))
    tool_registry.register(GetYouTubeTopVideosTool(youtube_repository))
    tool_registry.register(GetYouTubeTopChannelsTool(youtube_repository))

    return tool_registry
