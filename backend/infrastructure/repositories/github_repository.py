"""GitHub データ取得リポジトリ。

GitHub Worklogデータへのアクセスを提供します。
DuckDB を使用して R2 の Parquet ファイルから直接データを取得します。
"""

import logging
from datetime import date
from typing import Any

from backend.config import R2Config
from backend.infrastructure.database import (
    DuckDBConnection,
    GitHubQueryParams,
    get_activity_stats,
    get_commits,
    get_pull_requests,
    get_repositories,
    get_repo_summary_stats,
)

logger = logging.getLogger(__name__)


class GitHubRepository:
    """GitHub データ取得リポジトリ。

    DuckDB を使用して GitHub Worklogデータを取得します。
    R2 上の Parquet ファイルに直接クエリを発行します。
    """

    def __init__(self, r2_config: R2Config):
        """GitHubRepository を初期化します。

        Args:
            r2_config: R2 設定
        """
        self.r2_config = r2_config

    def get_pull_requests(
        self,
        start_date: date,
        end_date: date,
        owner: str | None = None,
        repo: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """指定期間のPull Requestイベントを取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            owner: フィルタ対象のオーナー（オプション）
            repo: フィルタ対象のリポジトリ（オプション）
            state: フィルタ対象の状態（open/closed、オプション）
            limit: 取得するPR数（デフォルト: 100）

        Returns:
            PRイベントのリスト（updated_at_utc DESC）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        with DuckDBConnection(self.r2_config) as conn:
            params = GitHubQueryParams(
                conn=conn,
                bucket=self.r2_config.bucket_name,
                events_path=self.r2_config.events_path,
                master_path=self.r2_config.master_path,
                start_date=start_date,
                end_date=end_date,
            )
            result = get_pull_requests(params, owner=owner, repo=repo, state=state, limit=limit)
            logger.info(
                "Retrieved pull requests: start_date=%s, end_date=%s, owner=%s, repo=%s, state=%s, limit=%s, count=%s",
                start_date,
                end_date,
                owner,
                repo,
                state,
                limit,
                len(result),
            )
            return result

    def get_commits(
        self,
        start_date: date,
        end_date: date,
        owner: str | None = None,
        repo: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """指定期間のCommitイベントを取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            owner: フィルタ対象のオーナー（オプション）
            repo: フィルタ対象のリポジトリ（オプション）
            limit: 取得するCommit数（デフォルト: 100）

        Returns:
            Commitイベントのリスト（committed_at_utc DESC）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        with DuckDBConnection(self.r2_config) as conn:
            params = GitHubQueryParams(
                conn=conn,
                bucket=self.r2_config.bucket_name,
                events_path=self.r2_config.events_path,
                master_path=self.r2_config.master_path,
                start_date=start_date,
                end_date=end_date,
            )
            result = get_commits(params, owner=owner, repo=repo, limit=limit)
            logger.info(
                "Retrieved commits: start_date=%s, end_date=%s, owner=%s, repo=%s, limit=%s, count=%s",
                start_date,
                end_date,
                owner,
                repo,
                limit,
                len(result),
            )
            return result

    def get_repositories(self, owner: str | None = None) -> list[dict[str, Any]]:
        """Repositoryマスターを取得します。

        Args:
            owner: フィルタ対象のオーナー（オプション）

        Returns:
            Repositoryリスト（updated_at_utc DESC）

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        with DuckDBConnection(self.r2_config) as conn:
            params = GitHubQueryParams(
                conn=conn,
                bucket=self.r2_config.bucket_name,
                events_path=self.r2_config.events_path,
                master_path=self.r2_config.master_path,
                start_date=date.min,
                end_date=date.max,
            )
            result = get_repositories(params, owner=owner)
            logger.info(
                "Retrieved repositories: owner=%s, count=%s",
                owner,
                len(result),
            )
            return result

    def get_activity_stats(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "day",
    ) -> list[dict[str, Any]]:
        """期間別のアクティビティ統計を取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            granularity: 集計単位（"day", "week", "month"）

        Returns:
            期間別統計のリスト

        Raises:
            duckdb.Error: データベース操作に失敗した場合
            ValueError: granularityが無効な場合
        """
        with DuckDBConnection(self.r2_config) as conn:
            params = GitHubQueryParams(
                conn=conn,
                bucket=self.r2_config.bucket_name,
                events_path=self.r2_config.events_path,
                master_path=self.r2_config.master_path,
                start_date=start_date,
                end_date=end_date,
            )
            result = get_activity_stats(params, granularity=granularity)
            logger.info(
                "Retrieved activity stats: start_date=%s, end_date=%s, granularity=%s, count=%s",
                start_date,
                end_date,
                granularity,
                len(result),
            )
            return result

    def get_repo_summary_stats(
        self,
        start_date: date,
        end_date: date,
        owner: str | None = None,
        repo_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """リポジトリ別のサマリー統計を取得します。

        Args:
            start_date: 開始日
            end_date: 終了日
            owner: フィルタ対象のオーナー（オプション）
            repo_name: フィルタ対象のリポジトリ名（オプション）

        Returns:
            リポジトリ別統計のリスト

        Raises:
            duckdb.Error: データベース操作に失敗した場合
        """
        with DuckDBConnection(self.r2_config) as conn:
            params = GitHubQueryParams(
                conn=conn,
                bucket=self.r2_config.bucket_name,
                events_path=self.r2_config.events_path,
                master_path=self.r2_config.master_path,
                start_date=start_date,
                end_date=end_date,
            )
            result = get_repo_summary_stats(params, owner=owner, repo_name=repo_name)
            logger.info(
                "Retrieved repo summary stats: start_date=%s, end_date=%s, owner=%s, repo=%s, count=%s",
                start_date,
                end_date,
                owner,
                repo_name,
                len(result),
            )
            return result
