"""Repository implementations.

リポジトリインターフェースの具体的な実装を提供します。
"""

from backend.infrastructure.repositories.browser_history_repository import (
    BrowserHistoryRepository,
)
from backend.infrastructure.repositories.github_repository import GitHubRepository
from backend.infrastructure.repositories.spotify_repository import SpotifyRepository
from backend.infrastructure.repositories.youtube_repository import YouTubeRepository

__all__ = [
    "BrowserHistoryRepository",
    "GitHubRepository",
    "SpotifyRepository",
    "YouTubeRepository",
]
