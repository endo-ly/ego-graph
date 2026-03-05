"""API/GitHub統合テスト（REDフェーズ）。"""

from unittest.mock import patch


class TestPullRequestsEndpoint:
    """Pull Requestsエンドポイントのテスト。"""

    def test_get_pull_requests_success(self, test_client, mock_db_and_parquet):
        """Pull Requestイベントを取得できる。"""
        mock_result = [
            {
                "pr_event_id": "pr_event_1",
                "pr_key": "pr_key_1",
                "owner": "test_owner",
                "repo": "test_repo",
                "repo_full_name": "test_owner/test_repo",
                "pr_number": 1,
                "pr_id": 101,
                "action": "opened",
                "state": "open",
                "is_merged": False,
                "title": "Test PR",
                "labels": ["bug"],
                "base_ref": "main",
                "head_ref": "feature-1",
                "created_at_utc": "2024-01-01T10:00:00",
                "updated_at_utc": "2024-01-01T10:00:00",
                "closed_at_utc": None,
                "merged_at_utc": None,
                "comments_count": 5,
                "review_comments_count": 2,
                "reviews_count": 1,
                "commits_count": 3,
                "additions": 100,
                "deletions": 20,
                "changed_files_count": 5,
            }
        ]

        with patch("backend.api.github.get_pull_requests", return_value=mock_result):
            response = test_client.get(
                "/v1/data/github/pull-requests?start_date=2024-01-01&end_date=2024-01-31&limit=10",
                headers={"X-API-Key": "test-backend-key"},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) > 0
            assert "pr_event_id" in data[0]
            assert "owner" in data[0]
            assert "pr_number" in data[0]
            assert "title" in data[0]

    def test_get_pull_requests_requires_api_key(self, test_client):
        """API Keyが必要。"""
        response = test_client.get(
            "/v1/data/github/pull-requests?start_date=2024-01-01&end_date=2024-01-31&limit=10"
        )

        assert response.status_code == 401

    def test_get_pull_requests_validates_limit(self, test_client):
        """limitの範囲バリデーション。"""
        # limit > 100
        response = test_client.get(
            "/v1/data/github/pull-requests?start_date=2024-01-01&end_date=2024-01-31&limit=101",
            headers={"X-API-Key": "test-backend-key"},
        )
        assert response.status_code == 422

    def test_get_pull_requests_requires_dates(self, test_client):
        """start_date/end_dateが必須。"""
        response = test_client.get(
            "/v1/data/github/pull-requests?limit=10",
            headers={"X-API-Key": "test-backend-key"},
        )

        assert response.status_code == 422


class TestCommitsEndpoint:
    """Commitsエンドポイントのテスト。"""

    def test_get_commits_success(self, test_client, mock_db_and_parquet):
        """Commitイベントを取得できる。"""
        mock_result = [
            {
                "commit_event_id": "commit_1",
                "owner": "test_owner",
                "repo": "test_repo",
                "repo_full_name": "test_owner/test_repo",
                "sha": "abc123",
                "message": "Test commit",
                "committed_at_utc": "2024-01-01T10:00:00",
                "changed_files_count": 5,
                "additions": 100,
                "deletions": 20,
            }
        ]

        with patch("backend.api.github.get_commits", return_value=mock_result):
            response = test_client.get(
                "/v1/data/github/commits?start_date=2024-01-01&end_date=2024-01-31&limit=10",
                headers={"X-API-Key": "test-backend-key"},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) > 0
            assert "commit_event_id" in data[0]
            assert "owner" in data[0]
            assert "sha" in data[0]
            assert "message" in data[0]

    def test_get_commits_requires_api_key(self, test_client):
        """API Keyが必要。"""
        response = test_client.get(
            "/v1/data/github/commits?start_date=2024-01-01&end_date=2024-01-31&limit=10"
        )

        assert response.status_code == 401


class TestRepositoriesEndpoint:
    """Repositoriesエンドポイントのテスト。"""

    def test_get_repositories_success(self, test_client, mock_db_and_parquet):
        """Repositoryマスターを取得できる。"""
        mock_result = [
            {
                "repo_id": 101,
                "owner": "test_owner",
                "repo": "test_repo",
                "repo_full_name": "test_owner/test_repo",
                "description": "Test repository",
                "is_private": False,
                "is_fork": False,
                "archived": False,
                "primary_language": "Python",
                "topics": ["test", "demo"],
                "stargazers_count": 10,
                "forks_count": 2,
                "open_issues_count": 3,
                "size_kb": 100,
                "created_at_utc": "2023-01-01T10:00:00",
                "updated_at_utc": "2024-01-01T10:00:00",
                "pushed_at_utc": "2024-01-01T10:00:00",
                "repo_summary_text": "Test repo summary",
                "summary_source": "manual",
            }
        ]

        with patch("backend.api.github.get_repositories", return_value=mock_result):
            response = test_client.get(
                "/v1/data/github/repositories",
                headers={"X-API-Key": "test-backend-key"},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) > 0
            assert "repo_id" in data[0]
            assert "owner" in data[0]
            assert "repo" in data[0]
            assert "primary_language" in data[0]

    def test_get_repositories_requires_api_key(self, test_client):
        """API Keyが必要。"""
        response = test_client.get("/v1/data/github/repositories")

        assert response.status_code == 401


class TestActivityStatsEndpoint:
    """Activity Statsエンドポイントのテスト。"""

    def test_get_activity_stats_success(self, test_client, mock_db_and_parquet):
        """アクティビティ統計を取得できる。"""
        mock_result = [
            {
                "period": "2024-01-01",
                "prs_created": 5,
                "prs_merged": 3,
                "commits_count": 10,
                "additions": 500,
                "deletions": 100,
            }
        ]

        with patch("backend.api.github.get_activity_stats", return_value=mock_result):
            response = test_client.get(
                "/v1/data/github/activity-stats?start_date=2024-01-01&end_date=2024-01-31&granularity=day",
                headers={"X-API-Key": "test-backend-key"},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) > 0
            assert "period" in data[0]
            assert "prs_created" in data[0]
            assert "prs_merged" in data[0]
            assert "commits_count" in data[0]

    def test_get_activity_stats_requires_api_key(self, test_client):
        """API Keyが必要。"""
        response = test_client.get(
            "/v1/data/github/activity-stats?start_date=2024-01-01&end_date=2024-01-31&granularity=day"
        )

        assert response.status_code == 401

    def test_get_activity_stats_validates_granularity(self, test_client):
        """granularityのバリデーション。"""
        response = test_client.get(
            "/v1/data/github/activity-stats?start_date=2024-01-01&end_date=2024-01-31&granularity=invalid",
            headers={"X-API-Key": "test-backend-key"},
        )

        assert response.status_code == 422


class TestRepoSummaryStatsEndpoint:
    """Repo Summary Statsエンドポイントのテスト。"""

    def test_get_repo_summary_stats_success(self, test_client, mock_db_and_parquet):
        """リポジトリ別統計を取得できる。"""
        mock_result = [
            {
                "owner": "test_owner",
                "repo": "test_repo",
                "repo_full_name": "test_owner/test_repo",
                "prs_total": 10,
                "prs_merged": 7,
                "commits_total": 50,
                "total_additions": 1000,
                "total_deletions": 200,
                "last_pr_updated_at": "2024-01-31T10:00:00",
                "last_commit_at": "2024-01-31T11:00:00",
            }
        ]

        with patch("backend.api.github.get_repo_summary_stats", return_value=mock_result):
            response = test_client.get(
                "/v1/data/github/repo-summary-stats?start_date=2024-01-01&end_date=2024-01-31",
                headers={"X-API-Key": "test-backend-key"},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) > 0
            assert "owner" in data[0]
            assert "repo" in data[0]
            assert "prs_total" in data[0]
            assert "commits_total" in data[0]

    def test_get_repo_summary_stats_requires_api_key(self, test_client):
        """API Keyが必要。"""
        response = test_client.get(
            "/v1/data/github/repo-summary-stats?start_date=2024-01-01&end_date=2024-01-31"
        )

        assert response.status_code == 401
