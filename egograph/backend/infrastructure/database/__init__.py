"""Infrastructure Database Layer.

DuckDB 接続管理とクエリユーティリティを提供します。
"""

from backend.infrastructure.database.browser_history_queries import (
    get_page_views,
    get_top_domains,
)
from backend.infrastructure.database.connection import DuckDBConnection
from backend.infrastructure.database.github_queries import (
    get_activity_stats,
    get_commits,
    get_pull_requests,
    get_repo_summary_stats,
    get_repos_parquet_path,
    get_repositories,
)
from backend.infrastructure.database.parquet_paths import (
    build_dataset_glob,
    build_partition_paths,
)
from backend.infrastructure.database.queries import (
    get_listening_stats,
    get_parquet_path,
    get_top_tracks,
)
from backend.infrastructure.database.query_params import QueryParams, execute_query

__all__ = [
    # R2 Data Lake (DuckDB)
    "DuckDBConnection",
    # Browser History
    "get_page_views",
    "get_top_domains",
    # Spotify
    "QueryParams",
    "execute_query",
    "get_parquet_path",
    "get_top_tracks",
    "get_listening_stats",
    "build_partition_paths",
    "build_dataset_glob",
    # GitHub
    "get_pull_requests",
    "get_commits",
    "get_repositories",
    "get_repos_parquet_path",
    "get_activity_stats",
    "get_repo_summary_stats",
]
