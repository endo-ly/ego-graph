"""GitHub コレクタのテスト。"""

import re
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses
from pipelines.sources.github.collector import GitHubWorklogCollector
from pipelines.tests.fixtures.github_responses import (
    get_mock_commit_detail,
    get_mock_pr_commits,
    get_mock_pr_reviews,
    get_mock_pull_requests,
    get_mock_repository,
    get_mock_repository_commits,
    get_mock_user_repositories,
)
from tenacity import RetryError


class TestGitHubWorklogCollectorInit:
    """GitHubWorklogCollector 初期化のテスト。"""

    def test_init_with_required_params(self):
        """必須パラメータでの初期化をテストする。"""
        # Arrange & Act: コレクターを初期化
        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Assert: 設定が正しく保存されていることを検証
        assert collector.token == "test_token"
        assert collector.github_login == "test-user"
        assert collector.base_url == "https://api.github.com"

    def test_init_with_custom_base_url(self):
        """カスタム base_url での初期化をテストする。"""
        # Arrange & Act: カスタム base_url で初期化
        collector = GitHubWorklogCollector(
            token="test_token",
            github_login="test-user",
            base_url="https://github.example.com/api/v3",
        )

        # Assert: base_url が正しく設定されていることを検証
        assert collector.base_url == "https://github.example.com/api/v3"

    def test_session_headers_configured(self):
        """セッションヘッダーが正しく設定されることをテストする。"""
        # Arrange & Act: モックされたセッションを検証
        mock_session = MagicMock()
        with patch(
            "pipelines.sources.github.collector.requests.Session",
            return_value=mock_session,
        ):
            _collector = GitHubWorklogCollector(
                token="test_token", github_login="test-user"
            )

            # Assert: Authorization ヘッダーと Accept ヘッダーが設定されている
            assert mock_session.headers.update.called
            call_args = mock_session.headers.update.call_args
            headers = call_args[0][0] if call_args[0] else call_args[1]
            assert headers["Authorization"] == "Bearer test_token"
            assert headers["Accept"] == "application/vnd.github+json"

    def test_init_raises_when_token_is_empty(self):
        """token が空文字の場合に ValueError になることをテストする。"""
        with pytest.raises(ValueError, match="GitHub token is required"):
            GitHubWorklogCollector(token="", github_login="test-user")

    def test_init_raises_when_github_login_is_empty(self):
        """github_login が空文字の場合に ValueError になることをテストする。"""
        with pytest.raises(ValueError, match="GitHub login is required"):
            GitHubWorklogCollector(token="test_token", github_login="")


class TestGetRepository:
    """get_repository メソッドのテスト。"""

    @responses.activate
    def test_get_repository_success(self):
        """Repository取得成功をテストする。"""
        # Arrange: モックレスポンスを設定
        mock_repo = get_mock_repository("test-user", "test-repo")
        responses.get(
            "https://api.github.com/repos/test-user/test-repo",
            json=mock_repo,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: Repositoryを取得
        result = collector.get_repository("test-user", "test-repo")

        # Assert: 結果を検証
        assert result["full_name"] == "test-user/test-repo"
        assert result["name"] == "test-repo"
        assert result["owner"]["login"] == "test-user"

    @responses.activate
    def test_get_repository_not_found(self):
        """Repositoryが見つからない場合をテストする。"""
        # Arrange: 404レスポンスをモック
        responses.get(
            "https://api.github.com/repos/test-user/nonexistent",
            json={"message": "Not Found"},
            status=404,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act & Assert: 例外が発生することを検証
        # リトライデコレータによりRetryErrorがスローされる
        with pytest.raises(RetryError):
            collector.get_repository("test-user", "nonexistent")


class TestGetPullRequests:
    """get_pull_requests メソッドのテスト。"""

    @responses.activate
    def test_get_pull_requests_success(self):
        """PR一覧取得成功をテストする。"""
        # Arrange: モックレスポンスを設定
        mock_prs = [get_mock_pull_requests(1)]
        responses.get(
            re.compile(r"https://api\.github\.com/repos/[^/]+/[^/]+/pulls"),
            json=mock_prs,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: PR一覧を取得
        result = collector.get_pull_requests("test-user", "test-repo")

        # Assert: 結果を検証
        assert len(result) == 1
        assert result[0]["title"] == "Test PR"
        assert result[0]["number"] == 1

    @responses.activate
    def test_get_pull_requests_with_state_filter(self):
        """stateフィルタを指定したPR取得をテストする。"""
        # Arrange: state=closed を含むリクエストをモック
        mock_prs = []
        responses.add(
            responses.GET,
            re.compile(
                r"https://api\.github\.com/repos/test-user/test-repo/pulls\?.*state=closed.*"
            ),
            json=mock_prs,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: closed状態のPRを取得
        result = collector.get_pull_requests("test-user", "test-repo", state="closed")

        # Assert: 結果を検証
        assert len(result) == 0

    @responses.activate
    def test_get_pull_requests_pagination(self):
        """PRページネーションをテストする。"""
        # Arrange: 複数ページのレスポンスをモック
        page1 = [get_mock_pull_requests(1), get_mock_pull_requests(1)]
        page2 = [get_mock_pull_requests(1)]

        # page=1 のリクエストをモック
        responses.add(
            responses.GET,
            re.compile(
                r"https://api\.github\.com/repos/test-user/test-repo/pulls\?.*page=1.*"
            ),
            json=page1,
            status=200,
        )
        # page=2 のリクエストをモック
        responses.add(
            responses.GET,
            re.compile(
                r"https://api\.github\.com/repos/test-user/test-repo/pulls\?.*page=2.*"
            ),
            json=page2,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: PR一覧を取得（ページネーション）
        result = collector.get_pull_requests("test-user", "test-repo", per_page=2)

        # Assert: 2ページ分が結合されていることを検証
        assert len(result) == 3


class TestGetPRCommits:
    """get_pr_commits メソッドのテスト。"""

    @responses.activate
    def test_get_pr_commits_success(self):
        """PR Commits取得成功をテストする。"""
        # Arrange: モックレスポンスを設定
        mock_commits = get_mock_pr_commits(2)
        responses.get(
            "https://api.github.com/repos/test-user/test-repo/pulls/1/commits",
            json=mock_commits,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: PR Commitsを取得
        result = collector.get_pr_commits("test-user", "test-repo", 1)

        # Assert: 結果を検証
        assert len(result) == 2
        assert result[0]["sha"] == "abc123def456"
        assert result[0]["commit"]["message"] == "Test commit message"

    @responses.activate
    def test_get_pr_commits_pagination(self):
        """PR Commitsページネーションをテストする。"""
        # Arrange: 複数ページのレスポンスをモック
        page1 = get_mock_pr_commits(2)
        page2 = [get_mock_pr_commits(1)[0]]

        # page=1 のリクエストをモック
        responses.add(
            responses.GET,
            re.compile(
                r"https://api\.github\.com/repos/test-user/test-repo/pulls/1/commits\?.*page=1.*"
            ),
            json=page1,
            status=200,
        )
        # page=2 のリクエストをモック
        responses.add(
            responses.GET,
            re.compile(
                r"https://api\.github\.com/repos/test-user/test-repo/pulls/1/commits\?.*page=2.*"
            ),
            json=page2,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: PR Commitsを取得（per_page=2でページネーション）
        result = collector.get_pr_commits("test-user", "test-repo", 1, per_page=2)

        # Assert: 2ページ分が結合されていることを検証
        assert len(result) == 3


class TestGetRepositoryCommits:
    """get_repository_commits メソッドのテスト。"""

    @responses.activate
    def test_get_repository_commits_success(self):
        """Repository Commits取得成功をテストする。"""
        # Arrange: モックレスポンスを設定
        mock_commits = get_mock_repository_commits(2)
        responses.get(
            "https://api.github.com/repos/test-user/test-repo/commits",
            json=mock_commits,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: Repository Commitsを取得
        result = collector.get_repository_commits("test-user", "test-repo")

        # Assert: 結果を検証
        assert len(result) == 1


class TestGetPRReviews:
    """get_pr_reviews メソッドのテスト。"""

    @responses.activate
    def test_get_pr_reviews_success(self):
        """PR Reviews取得成功をテストする。"""
        # Arrange: モックレスポンスを設定
        mock_reviews = get_mock_pr_reviews(2)
        responses.get(
            "https://api.github.com/repos/test-user/test-repo/pulls/1/reviews",
            json=mock_reviews,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: PR Reviewsを取得
        result = collector.get_pr_reviews("test-user", "test-repo", 1)

        # Assert: 結果を検証
        assert len(result) == 2
        assert result[0]["state"] == "APPROVED"
        assert result[1]["state"] == "CHANGES_REQUESTED"


class TestGetCommitDetail:
    """get_commit_detail メソッドのテスト。"""

    @responses.activate
    def test_get_commit_detail_success(self):
        """Commit Detail取得成功をテストする。"""
        # Arrange: モックレスポンスを設定
        mock_commit = get_mock_commit_detail()
        responses.get(
            "https://api.github.com/repos/test-user/test-repo/commits/abc123def456",
            json=mock_commit,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: Commit Detailを取得
        result = collector.get_commit_detail("test-user", "test-repo", "abc123def456")

        # Assert: 結果を検証
        assert result["sha"] == "abc123def456"
        assert result["stats"]["additions"] == 50
        assert result["stats"]["deletions"] == 20
        assert len(result["files"]) == 2


class TestGetUserRepositories:
    """get_user_repositories メソッドのテスト。"""

    @responses.activate
    def test_get_user_repositories_filters_by_owner(self):
        """github_loginと一致するownerのRepoのみフィルタすることをテストする。"""
        # Arrange: 複数ユーザーのRepoを含むレスポンスをモック
        mock_repos = get_mock_user_repositories()
        responses.get(
            "https://api.github.com/user/repos",
            json=mock_repos,
            status=200,
        )

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: User Repositoriesを取得
        result = collector.get_user_repositories()

        # Assert: test-userのRepoのみが含まれることを検証
        assert len(result) == 1
        assert result[0]["full_name"] == "test-user/test-repo"
        assert result[0]["owner"]["login"] == "test-user"


class TestRetryDecorator:
    """リトライデコレータのテスト。"""

    @patch("pipelines.sources.github.collector.requests.Session")
    def test_retry_on_request_exception(self, mock_session_class):
        """リクエスト例外時のリトライをテストする。"""
        # Arrange: 最初の2回は失敗、3回目は成功
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        mock_session.get.side_effect = [
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
            mock_response,
        ]

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act: リトライデコレータ付きメソッドを実行
        result = collector.get_repository("test-user", "test-repo")

        # Assert: 3回呼び出され、最終的に成功していることを検証
        assert mock_session.get.call_count == 3
        assert result is not None

    @patch("pipelines.sources.github.collector.requests.Session")
    def test_retry_exhausted(self, mock_session_class):
        """リトライ回数超過時の動作をテストする。"""
        # Arrange: 常に失敗するモック
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError()

        collector = GitHubWorklogCollector(token="test_token", github_login="test-user")

        # Act & Assert: リトライ上限超過でRetryErrorが発生することを検証
        with pytest.raises(RetryError):
            collector.get_repository("test-user", "test-repo")

        # Assert: リトライ回数分呼び出されていることを検証
        assert mock_session.get.call_count == 3
