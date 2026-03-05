"""GitHub Worklog ツール。

指定期間のGitHub作業ログを取得するツールを提供します。
"""

import logging
from typing import Any

from backend.constants import MAX_LIMIT
from backend.domain.models.tool import ToolBase
from backend.infrastructure.repositories import GitHubRepository
from backend.validators import (
    validate_date_range,
    validate_granularity,
    validate_limit,
)

logger = logging.getLogger(__name__)


class GetPullRequestsTool(ToolBase):
    """指定期間のPull Requestイベントを取得するツール。"""

    def __init__(self, repository: GitHubRepository):
        """GetPullRequestsTool を初期化します。

        Args:
            repository: GitHub データリポジトリ
        """
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_pull_requests"

    @property
    def description(self) -> str:
        return (
            "GitHubの指定した期間（start_date から end_date）の "
            "Pull Requestイベントを取得します。更新日時の降順でソートされます。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "開始日（ISO形式: YYYY-MM-DD）",
                },
                "end_date": {
                    "type": "string",
                    "description": "終了日（ISO形式: YYYY-MM-DD）",
                },
                "owner": {
                    "type": "string",
                    "description": "フィルタ対象のオーナー（オプション）",
                },
                "repo": {
                    "type": "string",
                    "description": "フィルタ対象のリポジトリ（オプション）",
                },
                "state": {
                    "type": "string",
                    "description": "フィルタ対象の状態（open/closed、オプション）",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得するPR数（デフォルト: 100）",
                },
            },
            "required": ["start_date", "end_date"],
        }

    def execute(
        self,
        start_date: str,
        end_date: str,
        owner: str | None = None,
        repo: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Pull Requestイベントを取得します。

        Args:
            start_date: 開始日（ISO形式: YYYY-MM-DD）
            end_date: 終了日（ISO形式: YYYY-MM-DD）
            owner: フィルタ対象のオーナー（オプション）
            repo: フィルタ対象のリポジトリ（オプション）
            state: フィルタ対象の状態（オプション）
            limit: 取得するPR数

        Returns:
            PRイベントのリスト

        Raises:
            ValueError: 日付形式が不正な場合
        """
        # バリデーション（ビジネスロジック）
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)

        logger.info(
            "Executing get_pull_requests: %s to %s, owner=%s, repo=%s, state=%s, limit=%s",
            start,
            end,
            owner,
            repo,
            state,
            validated_limit,
        )

        # データ取得は repository に委譲
        return self.repository.get_pull_requests(
            start, end, owner=owner, repo=repo, state=state, limit=validated_limit
        )


class GetCommitsTool(ToolBase):
    """指定期間のCommitイベントを取得するツール。"""

    def __init__(self, repository: GitHubRepository):
        """GetCommitsTool を初期化します。

        Args:
            repository: GitHub データリポジトリ
        """
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_commits"

    @property
    def description(self) -> str:
        return (
            "GitHubの指定した期間（start_date から end_date）の "
            "Commitイベントを取得します。コミット日時の降順でソートされます。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "開始日（ISO形式: YYYY-MM-DD）",
                },
                "end_date": {
                    "type": "string",
                    "description": "終了日（ISO形式: YYYY-MM-DD）",
                },
                "owner": {
                    "type": "string",
                    "description": "フィルタ対象のオーナー（オプション）",
                },
                "repo": {
                    "type": "string",
                    "description": "フィルタ対象のリポジトリ（オプション）",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得するCommit数（デフォルト: 100）",
                },
            },
            "required": ["start_date", "end_date"],
        }

    def execute(
        self,
        start_date: str,
        end_date: str,
        owner: str | None = None,
        repo: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Commitイベントを取得します。

        Args:
            start_date: 開始日（ISO形式: YYYY-MM-DD）
            end_date: 終了日（ISO形式: YYYY-MM-DD）
            owner: フィルタ対象のオーナー（オプション）
            repo: フィルタ対象のリポジトリ（オプション）
            limit: 取得するCommit数

        Returns:
            Commitイベントのリスト

        Raises:
            ValueError: 日付形式が不正な場合
        """
        # バリデーション（ビジネスロジック）
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)

        logger.info(
            "Executing get_commits: %s to %s, owner=%s, repo=%s, limit=%s",
            start,
            end,
            owner,
            repo,
            validated_limit,
        )

        # データ取得は repository に委譲
        return self.repository.get_commits(
            start, end, owner=owner, repo=repo, limit=validated_limit
        )


class GetRepositoriesTool(ToolBase):
    """Repositoryマスターを取得するツール。"""

    def __init__(self, repository: GitHubRepository):
        """GetRepositoriesTool を初期化します。

        Args:
            repository: GitHub データリポジトリ
        """
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_repositories"

    @property
    def description(self) -> str:
        return (
            "GitHubのRepositoryマスターを取得します。"
            "オーナーでフィルタすることもできます。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "フィルタ対象のオーナー（オプション）",
                },
                "repo": {
                    "type": "string",
                    "description": "フィルタ対象のリポジトリ（オプション）",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得するリポジトリ数（デフォルト: 10）",
                },
            },
        }

    def execute(
        self,
        owner: str | None = None,
        repo: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Repositoryマスターを取得します。

        Args:
            owner: フィルタ対象のオーナー（オプション）
            repo: フィルタ対象のリポジトリ（オプション）

        Returns:
            Repositoryリスト
        """
        logger.info("Executing get_repositories: owner=%s, repo=%s, limit=%s", owner, repo, limit)

        # データ取得は repository に委譲
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
        result = self.repository.get_repositories(owner=owner)
        return result[:validated_limit]


class GetActivityStatsTool(ToolBase):
    """期間別のアクティビティ統計を取得するツール。"""

    def __init__(self, repository: GitHubRepository):
        """GetActivityStatsTool を初期化します。

        Args:
            repository: GitHub データリポジトリ
        """
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_activity_stats"

    @property
    def description(self) -> str:
        return (
            "GitHubの指定した期間のアクティビティ統計を取得します。"
            "日別、週別、月別で集計できます。"
            "PR作成数、PRマージ数、Commit数、追加・削除行数を返します。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "開始日（ISO形式: YYYY-MM-DD）",
                },
                "end_date": {
                    "type": "string",
                    "description": "終了日（ISO形式: YYYY-MM-DD）",
                },
                "granularity": {
                    "type": "string",
                    "description": "集計単位",
                    "enum": ["day", "week", "month"],
                },
            },
            "required": ["start_date", "end_date"],
        }

    def execute(
        self,
        start_date: str,
        end_date: str,
        granularity: str = "day",
    ) -> list[dict[str, Any]]:
        """アクティビティ統計を取得します。

        Args:
            start_date: 開始日（ISO形式: YYYY-MM-DD）
            end_date: 終了日（ISO形式: YYYY-MM-DD）
            granularity: 集計単位（"day", "week", "month"）

        Returns:
            期間別統計のリスト

        Raises:
            ValueError: 日付形式または granularity が不正な場合
        """
        # バリデーション（ビジネスロジック）
        start, end = validate_date_range(start_date, end_date)
        validated_granularity = validate_granularity(granularity)

        logger.info(
            "Executing get_activity_stats: %s to %s, granularity=%s",
            start,
            end,
            granularity,
        )

        # データ取得は repository に委譲
        return self.repository.get_activity_stats(start, end, validated_granularity)


class GetRepoSummaryStatsTool(ToolBase):
    """リポジトリ別のサマリー統計を取得するツール。"""

    def __init__(self, repository: GitHubRepository):
        """GetRepoSummaryStatsTool を初期化します。

        Args:
            repository: GitHub データリポジトリ
        """
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_repo_summary_stats"

    @property
    def description(self) -> str:
        return (
            "GitHubの指定した期間のリポジトリ別統計を取得します。"
            "各リポジトリのPR数、Commit数、追加・削除行数を返します。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "開始日（ISO形式: YYYY-MM-DD）",
                },
                "end_date": {
                    "type": "string",
                    "description": "終了日（ISO形式: YYYY-MM-DD）",
                },
                "owner": {
                    "type": "string",
                    "description": "フィルタ対象のオーナー（オプション）",
                },
                "repo": {
                    "type": "string",
                    "description": "フィルタ対象のリポジトリ（オプション）",
                },
            },
            "required": ["start_date", "end_date"],
        }

    def execute(
        self,
        start_date: str,
        end_date: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> list[dict[str, Any]]:
        """リポジトリ別統計を取得します。

        Args:
            start_date: 開始日（ISO形式: YYYY-MM-DD）
            end_date: 終了日（ISO形式: YYYY-MM-DD）
            owner: フィルタ対象のオーナー（オプション）
            repo: フィルタ対象のリポジトリ（オプション）

        Returns:
            リポジトリ別統計のリスト

        Raises:
            ValueError: 日付形式が不正な場合
        """
        # バリデーション（ビジネスロジック）
        start, end = validate_date_range(start_date, end_date)

        logger.info(
            "Executing get_repo_summary_stats: %s to %s, owner=%s, repo=%s",
            start,
            end,
            owner,
            repo,
        )

        # データ取得は repository に委譲
        return self.repository.get_repo_summary_stats(start, end, owner=owner, repo_name=repo)
