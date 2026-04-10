"""API Schemas.

データ提供API用のリクエスト/レスポンススキーマを定義します。
"""

from backend.api.schemas.data import (
    ListeningStatsResponse,
    PageViewResponse,
    TopChannelResponse,
    TopDomainResponse,
    TopTrackResponse,
    WatchHistoryResponse,
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
    "WatchHistoryResponse",
    "WatchingStatsResponse",
    "TopDomainResponse",
    "TopChannelResponse",
    # GitHub API スキーマ
    "PullRequestResponse",
    "CommitResponse",
    "RepositoryResponse",
    "ActivityStatsResponse",
    "RepoSummaryStatsResponse",
]
