"""Tools/GitHub/Worklog層のテスト（REDフェーズ）。"""

from unittest.mock import MagicMock

import pytest

from backend.domain.tools.github.worklog import (
    GetActivityStatsTool,
    GetCommitsTool,
    GetPullRequestsTool,
    GetRepoSummaryStatsTool,
    GetRepositoriesTool,
)


class TestGetPullRequestsTool:
    """GetPullRequestsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetPullRequestsTool(mock_repository)

        # Assert: nameプロパティを検証
        assert tool.name == "get_pull_requests"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetPullRequestsTool(mock_repository)

        # Assert: descriptionプロパティを検証
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetPullRequestsTool(mock_repository)

        # Act: input_schemaを取得
        schema = tool.input_schema

        # Assert: スキーマ構造を検証
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "owner" in schema["properties"]
        assert "repo" in schema["properties"]
        assert "state" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_execute_with_valid_parameters(self):
        """正しいパラメータでexecute()を実行。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        mock_repository.get_pull_requests.return_value = [
            {
                "pr_event_id": "pr_event_1",
                "owner": "test_owner",
                "repo": "test_repo",
                "pr_number": 1,
                "title": "Test PR",
            }
        ]
        tool = GetPullRequestsTool(mock_repository)

        # Act: ツールを実行
        result = tool.execute(
            start_date="2024-01-01", end_date="2024-01-31", limit=10
        )

        # Assert: 実行結果とリポジトリ呼び出しを検証
        assert len(result) == 1
        assert result[0]["pr_number"] == 1
        mock_repository.get_pull_requests.assert_called_once()

    def test_execute_with_invalid_date_format_raises_error(self):
        """不正な日付形式でエラー。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetPullRequestsTool(mock_repository)

        # Act & Assert: 不正な日付形式でValueErrorが発生することを検証
        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="invalid-date", end_date="2024-01-31")


class TestGetCommitsTool:
    """GetCommitsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetCommitsTool(mock_repository)

        # Assert: nameプロパティを検証
        assert tool.name == "get_commits"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetCommitsTool(mock_repository)

        # Assert: descriptionプロパティを検証
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetCommitsTool(mock_repository)

        # Act: input_schemaを取得
        schema = tool.input_schema

        # Assert: スキーマ構造を検証
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "owner" in schema["properties"]
        assert "repo" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_execute_with_valid_parameters(self):
        """正しいパラメータでexecute()を実行。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        mock_repository.get_commits.return_value = [
            {
                "commit_event_id": "commit_1",
                "owner": "test_owner",
                "repo": "test_repo",
                "sha": "abc123",
                "message": "Test commit",
            }
        ]
        tool = GetCommitsTool(mock_repository)

        # Act: ツールを実行
        result = tool.execute(
            start_date="2024-01-01", end_date="2024-01-31", limit=10
        )

        # Assert: 実行結果とリポジトリ呼び出しを検証
        assert len(result) == 1
        assert result[0]["sha"] == "abc123"
        mock_repository.get_commits.assert_called_once()


class TestGetRepositoriesTool:
    """GetRepositoriesToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetRepositoriesTool(mock_repository)

        # Assert: nameプロパティを検証
        assert tool.name == "get_repositories"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetRepositoriesTool(mock_repository)

        # Assert: descriptionプロパティを検証
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetRepositoriesTool(mock_repository)

        # Act: input_schemaを取得
        schema = tool.input_schema

        # Assert: スキーマ構造を検証
        assert schema["type"] == "object"
        assert "owner" in schema["properties"]
        assert "repo" in schema["properties"]

    def test_execute_with_valid_parameters(self):
        """正しいパラメータでexecute()を実行。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        mock_repository.get_repositories.return_value = [
            {
                "repo_id": 101,
                "owner": "test_owner",
                "repo": "test_repo",
                "repo_full_name": "test_owner/test_repo",
            }
        ]
        tool = GetRepositoriesTool(mock_repository)

        # Act: ツールを実行
        result = tool.execute(owner="test_owner")

        # Assert: 実行結果とリポジトリ呼び出しを検証
        assert len(result) == 1
        assert result[0]["repo_id"] == 101
        mock_repository.get_repositories.assert_called_once()


class TestGetActivityStatsTool:
    """GetActivityStatsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetActivityStatsTool(mock_repository)

        # Assert: nameプロパティを検証
        assert tool.name == "get_activity_stats"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetActivityStatsTool(mock_repository)

        # Assert: descriptionプロパティを検証
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetActivityStatsTool(mock_repository)

        # Act: input_schemaを取得
        schema = tool.input_schema

        # Assert: スキーマ構造を検証
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "granularity" in schema["properties"]
        assert schema["properties"]["granularity"]["enum"] == ["day", "week", "month"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_execute_with_valid_parameters(self):
        """正しいパラメータでexecute()を実行。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        mock_repository.get_activity_stats.return_value = [
            {
                "period": "2024-01-01",
                "prs_created": 5,
                "prs_merged": 3,
                "commits_count": 10,
            }
        ]
        tool = GetActivityStatsTool(mock_repository)

        # Act: ツールを実行
        result = tool.execute(
            start_date="2024-01-01", end_date="2024-01-31", granularity="day"
        )

        # Assert: 実行結果とリポジトリ呼び出しを検証
        assert len(result) == 1
        assert result[0]["prs_created"] == 5
        mock_repository.get_activity_stats.assert_called_once()


class TestGetRepoSummaryStatsTool:
    """GetRepoSummaryStatsToolのテスト。"""

    def test_name_property(self):
        """nameプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetRepoSummaryStatsTool(mock_repository)

        # Assert: nameプロパティを検証
        assert tool.name == "get_repo_summary_stats"

    def test_description_property(self):
        """descriptionプロパティが正しい。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetRepoSummaryStatsTool(mock_repository)

        # Assert: descriptionプロパティを検証
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_input_schema_structure(self):
        """input_schemaが正しい構造を持つ。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        tool = GetRepoSummaryStatsTool(mock_repository)

        # Act: input_schemaを取得
        schema = tool.input_schema

        # Assert: スキーマ構造を検証
        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "owner" in schema["properties"]
        assert "repo" in schema["properties"]
        assert "start_date" in schema["required"]
        assert "end_date" in schema["required"]

    def test_execute_with_valid_parameters(self):
        """正しいパラメータでexecute()を実行。"""
        # Arrange: モックリポジトリとツールを準備
        mock_repository = MagicMock()
        mock_repository.get_repo_summary_stats.return_value = [
            {
                "owner": "test_owner",
                "repo": "test_repo",
                "prs_total": 10,
                "commits_total": 50,
            }
        ]
        tool = GetRepoSummaryStatsTool(mock_repository)

        # Act: ツールを実行
        result = tool.execute(
            start_date="2024-01-01", end_date="2024-01-31"
        )

        # Assert: 実行結果とリポジトリ呼び出しを検証
        assert len(result) == 1
        assert result[0]["prs_total"] == 10
        mock_repository.get_repo_summary_stats.assert_called_once()
