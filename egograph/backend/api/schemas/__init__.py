"""API Schemas.

データ提供API用のリクエスト/レスポンススキーマを定義します。
"""

from backend.api.schemas.data import (
    ListeningStatsResponse,
    PageViewResponse,
    TopChannelResponse,
    TopDomainResponse,
    TopTrackResponse,
    TopVideoResponse,
    WatchEventResponse,
    WatchingStatsResponse,
)
from backend.api.schemas.github import (
    ActivityStatsResponse,
    CommitResponse,
    PullRequestResponse,
    RepositoryResponse,
    RepoSummaryStatsResponse,
)

__all__ = [
    # Data API スキーマ
    "TopTrackResponse",
    "ListeningStatsResponse",
    "PageViewResponse",
    "WatchEventResponse",
    "WatchingStatsResponse",
    "TopDomainResponse",
    "TopChannelResponse",
    "TopVideoResponse",
    # GitHub API スキーマ
    "PullRequestResponse",
    "CommitResponse",
    "RepositoryResponse",
    "ActivityStatsResponse",
    "RepoSummaryStatsResponse",
]
