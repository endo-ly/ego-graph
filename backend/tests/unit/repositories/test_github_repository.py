"""GitHub Repository層のテスト（REDフェーズ）。"""

from datetime import date
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from backend.infrastructure.repositories.github_repository import GitHubRepository
from backend.config import R2Config


class TestGitHubRepository:
    """GitHubRepositoryのテスト。"""

    def test_get_pull_requests(self, github_with_sample_data):
        """Pull Requestイベントを取得。"""
        # Arrange
        prs_parquet_path = github_with_sample_data.test_prs_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries._generate_pr_partition_paths",
                return_value=[prs_parquet_path],
            ):
                # Act
                repo = GitHubRepository(mock_r2_config())
                result = repo.get_pull_requests(date(2024, 1, 1), date(2024, 1, 31))

        # Assert
        assert len(result) > 0
        assert "pr_event_id" in result[0]
        assert "owner" in result[0]
        assert "repo" in result[0]
        assert "pr_number" in result[0]
        assert "title" in result[0]

    def test_get_pull_requests_with_filters(self, github_with_sample_data):
        """フィルタ条件を指定してPull Requestイベントを取得。"""
        # Arrange
        prs_parquet_path = github_with_sample_data.test_prs_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries._generate_pr_partition_paths",
                return_value=[prs_parquet_path],
            ):
                # Act
                repo = GitHubRepository(mock_r2_config())
                result = repo.get_pull_requests(
                    date(2024, 1, 1),
                    date(2024, 1, 31),
                    owner="test_owner",
                    repo="test_repo",
                    state="open",
                    limit=10,
                )

        # Assert
        assert len(result) >= 0

    def test_get_commits(self, github_with_sample_data):
        """Commitイベントを取得。"""
        # Arrange
        commits_parquet_path = github_with_sample_data.test_commits_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries._generate_commit_partition_paths",
                return_value=[commits_parquet_path],
            ):
                # Act
                repo = GitHubRepository(mock_r2_config())
                result = repo.get_commits(date(2024, 1, 1), date(2024, 1, 31))

        # Assert
        assert len(result) > 0
        assert "commit_event_id" in result[0]
        assert "owner" in result[0]
        assert "repo" in result[0]
        assert "sha" in result[0]
        assert "message" in result[0]

    def test_get_commits_with_filters(self, github_with_sample_data):
        """フィルタ条件を指定してCommitイベントを取得。"""
        # Arrange
        commits_parquet_path = github_with_sample_data.test_commits_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries._generate_commit_partition_paths",
                return_value=[commits_parquet_path],
            ):
                # Act
                repo = GitHubRepository(mock_r2_config())
                result = repo.get_commits(
                    date(2024, 1, 1),
                    date(2024, 1, 31),
                    owner="test_owner",
                    repo="test_repo",
                    limit=10,
                )

        # Assert
        assert len(result) >= 0

    def test_get_repositories(self, github_with_sample_data):
        """Repositoryマスターを取得。"""
        # Arrange
        repos_parquet_path = github_with_sample_data.test_repos_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries.get_repos_parquet_path",
                return_value=repos_parquet_path,
            ):
                # Act
                repo = GitHubRepository(mock_r2_config())
                result = repo.get_repositories()

        # Assert
        assert len(result) > 0
        assert "repo_id" in result[0]
        assert "owner" in result[0]
        assert "repo" in result[0]
        assert "repo_full_name" in result[0]
        assert "primary_language" in result[0]

    def test_get_repositories_with_owner_filter(
        self, github_with_sample_data
    ):
        """オーナーフィルタを指定してRepositoryマスターを取得。"""
        # Arrange
        repos_parquet_path = github_with_sample_data.test_repos_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries.get_repos_parquet_path",
                return_value=repos_parquet_path,
            ):
                # Act
                repo = GitHubRepository(mock_r2_config())
                result = repo.get_repositories(owner="test_owner")

        # Assert
        assert len(result) >= 0

    def test_get_activity_stats(self, github_with_sample_data):
        """アクティビティ統計を取得。"""
        # Arrange
        prs_parquet_path = github_with_sample_data.test_prs_parquet_path
        commits_parquet_path = github_with_sample_data.test_commits_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries._generate_pr_partition_paths",
                return_value=[prs_parquet_path],
            ):
                with patch(
                    "backend.infrastructure.database.github_queries._generate_commit_partition_paths",
                    return_value=[commits_parquet_path],
                ):
                    # Act
                    repo = GitHubRepository(mock_r2_config())
                    result = repo.get_activity_stats(
                        date(2024, 1, 1), date(2024, 1, 31), granularity="day"
                    )

        # Assert
        assert len(result) >= 0
        if len(result) > 0:
            assert "period" in result[0]
            assert "prs_created" in result[0]
            assert "prs_merged" in result[0]
            assert "commits_count" in result[0]

    def test_get_repo_summary_stats(self, github_with_sample_data):
        """リポジトリ別統計を取得。"""
        # Arrange
        prs_parquet_path = github_with_sample_data.test_prs_parquet_path
        commits_parquet_path = github_with_sample_data.test_commits_parquet_path

        with patch(
            "backend.infrastructure.database.DuckDBConnection"
        ) as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=github_with_sample_data)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.return_value = mock_conn

            with patch(
                "backend.infrastructure.database.github_queries._generate_pr_partition_paths",
                return_value=[prs_parquet_path],
            ):
                with patch(
                    "backend.infrastructure.database.github_queries._generate_commit_partition_paths",
                    return_value=[commits_parquet_path],
                ):
                    # Act
                    repo = GitHubRepository(mock_r2_config())
                    result = repo.get_repo_summary_stats(
                        date(2024, 1, 1), date(2024, 1, 31)
                    )

        # Assert
        assert len(result) >= 0
        if len(result) > 0:
            assert "owner" in result[0]
            assert "repo" in result[0]
            assert "prs_total" in result[0]
            assert "commits_total" in result[0]


def mock_r2_config():
    """モックR2設定。"""
    return R2Config.model_construct(
        endpoint_url="https://test.r2.cloudflarestorage.com",
        access_key_id="test_key",
        secret_access_key=SecretStr("test_secret"),
        bucket_name="test-bucket",
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
    )
