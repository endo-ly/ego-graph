"""GitHubデータコレクター。

GitHub APIに接続し、以下を収集します:
- Repository情報
- Pull Requests
- PR Commits
- Repository Commits
- PR Reviews
- Commit Detail
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# 設定値は Spotify と同様のデフォルトを使用
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
DEFAULT_PER_PAGE = 100

logger = logging.getLogger(__name__)

# 共通リトライデコレータ
github_retry = retry(
    retry=retry_if_exception_type(
        (requests.exceptions.RequestException, requests.exceptions.HTTPError)
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=RETRY_BACKOFF_FACTOR, min=2, max=10),
)


@github_retry
def _get_json_with_retry(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """単一APIリクエストをリトライ付きで実行する。"""
    response = session.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _paginate(
    fetch_fn: Callable[..., dict[str, Any]],
    *,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """ページネーションを使用してすべてのアイテムを取得する汎用ヘルパー。

    GitHub API は Link ヘッダーを使用したページネーションを実装しています。

    Args:
        fetch_fn: ページ番号を受け取り、API レスポンス辞書を返す関数
        max_items: 取得する最大アイテム数 (None の場合は無制限)

    Returns:
        すべてのアイテムのリスト
    """
    items: list[dict[str, Any]] = []
    page = 1

    while True:
        results = fetch_fn(page=page)
        if not isinstance(results, dict):
            logger.warning(
                "Pagination fetch returned non-dict result; stopping. type=%s",
                type(results).__name__,
            )
            break

        # GitHub API は配列を直接返す場合と、オブジェクトでラップする場合がある
        page_items = results if isinstance(results, list) else results

        if isinstance(page_items, dict):
            page_items = page_items.get("items", [])

        if not page_items:
            break

        if max_items is not None:
            remaining = max_items - len(items)
            if remaining <= 0:
                break
            if len(page_items) > remaining:
                items.extend(page_items[:remaining])
                break
            items.extend(page_items)
        else:
            items.extend(page_items)

        # GitHub API のページネーションは Link ヘッダーで判断
        # fetch_fn 内で処理するため、ここでは簡易的に空配列で終了
        if len(page_items) < DEFAULT_PER_PAGE:
            break

        page += 1

    if max_items is not None:
        return items[:max_items]
    return items


def _parse_github_datetime(value: str | None) -> datetime | None:
    """GitHub日時文字列をdatetimeに変換する。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubWorklogCollector:
    """GitHub APIデータコレクター。

    GitHub REST APIからの認証とデータ収集を処理します。
    レート制限や一時的なエラーを処理するためのリトライロジックを実装しています。
    """

    def __init__(
        self,
        token: str,
        github_login: str,
        base_url: str = "https://api.github.com",
    ):
        """GitHubコレクターを初期化します。

        Args:
            token: GitHub Personal Access Token
            github_login: フィルタ対象のGitHubユーザー名（個人所有Repo判定用）
            base_url: GitHub APIベースURL
        """
        if not token.strip():
            raise ValueError("GitHub token is required")
        if not github_login.strip():
            raise ValueError("GitHub login is required")

        self.token = token
        self.github_login = github_login
        self.base_url = base_url.rstrip("/")

        # セッションの設定
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

        logger.info("GitHub collector initialized for user: %s", github_login)

    @github_retry
    def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        """Repository情報を取得します。

        Args:
            owner: リポジトリ所有者
            repo: リポジトリ名

        Returns:
            Repository情報を含む辞書

        Raises:
            requests.exceptions.HTTPError: API呼び出しが失敗した場合
        """
        logger.debug("Fetching repository: %s/%s", owner, repo)
        url = f"{self.base_url}/repos/{owner}/{repo}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        per_page: int = DEFAULT_PER_PAGE,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """指定RepoのPull Request一覧を取得します。

        Args:
            owner: リポジトリ所有者
            repo: リポジトリ名
            state: PRの状態 (all, open, closed)
            per_page: 1ページあたりのアイテム数

        Returns:
            Pull Request辞書のリスト

        Raises:
            requests.exceptions.HTTPError: API呼び出しが失敗した場合
        """
        logger.debug("Fetching pull requests for %s/%s (state=%s)", owner, repo, state)

        def fetch_page(page: int) -> list[dict[str, Any]]:
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
            params: dict[str, Any] = {
                "state": state,
                "per_page": per_page,
                "page": page,
                "sort": "updated",
                "direction": "desc",
            }
            return _get_json_with_retry(self.session, url, params)

        prs: list[dict[str, Any]] = []
        page = 1

        while True:
            page_data = fetch_page(page)
            if not page_data:
                break

            if since:
                since_dt = _parse_github_datetime(since)
                filtered_page: list[dict[str, Any]] = []
                for pr in page_data:
                    updated_dt = _parse_github_datetime(pr.get("updated_at"))
                    if since_dt is None or updated_dt is None or updated_dt >= since_dt:
                        filtered_page.append(pr)
                prs.extend(filtered_page)

                oldest_updated = _parse_github_datetime(page_data[-1].get("updated_at"))
                if (
                    since_dt is not None
                    and oldest_updated is not None
                    and oldest_updated < since_dt
                ):
                    break
            else:
                prs.extend(page_data)

            if len(page_data) < per_page:
                break
            page += 1

        logger.info(
            "Successfully fetched %d pull requests for %s/%s",
            len(prs),
            owner,
            repo,
        )
        return prs

    def get_pr_commits(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> list[dict[str, Any]]:
        """PRに含まれるCommit一覧を取得します。

        Args:
            owner: リポジトリ所有者
            repo: リポジトリ名
            pr_number: PR番号
            per_page: 1ページあたりのアイテム数

        Returns:
            Commit辞書のリスト

        Raises:
            requests.exceptions.HTTPError: API呼び出しが失敗した場合
        """
        logger.debug("Fetching commits for PR %s/%s#%d", owner, repo, pr_number)

        commits: list[dict[str, Any]] = []
        page = 1

        while True:
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/commits"
            params = {"per_page": per_page, "page": page}
            page_data = _get_json_with_retry(self.session, url, params)

            if not page_data:
                break
            commits.extend(page_data)
            if len(page_data) < per_page:
                break
            page += 1

        logger.debug(
            "Fetched %d commits for PR %s/%s#%d", len(commits), owner, repo, pr_number
        )
        return commits

    def get_repository_commits(
        self,
        owner: str,
        repo: str,
        per_page: int = DEFAULT_PER_PAGE,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """リポジトリの全Commitを取得します（PR外の直接push含む）。

        Args:
            owner: リポジトリ所有者
            repo: リポジトリ名
            per_page: 1ページあたりのアイテム数

        Returns:
            Commit辞書のリスト

        Raises:
            requests.exceptions.HTTPError: API呼び出しが失敗した場合
        """
        logger.debug("Fetching commits for repository %s/%s", owner, repo)

        commits: list[dict[str, Any]] = []
        page = 1

        while True:
            url = f"{self.base_url}/repos/{owner}/{repo}/commits"
            params: dict[str, Any] = {"per_page": per_page, "page": page}
            if since:
                params["since"] = since
            page_data = _get_json_with_retry(self.session, url, params)

            if not page_data:
                break
            commits.extend(page_data)
            if len(page_data) < per_page:
                break
            page += 1

        logger.info(
            "Successfully fetched %d commits for %s/%s", len(commits), owner, repo
        )
        return commits

    def get_pr_reviews(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> list[dict[str, Any]]:
        """PRのレビュー一覧を取得します。

        Args:
            owner: リポジトリ所有者
            repo: リポジトリ名
            pr_number: PR番号
            per_page: 1ページあたりのアイテム数

        Returns:
            Review辞書のリスト

        Raises:
            requests.exceptions.HTTPError: API呼び出しが失敗した場合
        """
        logger.debug("Fetching reviews for PR %s/%s#%d", owner, repo, pr_number)

        reviews: list[dict[str, Any]] = []
        page = 1

        while True:
            url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
            params = {"per_page": per_page, "page": page}
            page_data = _get_json_with_retry(self.session, url, params)

            if not page_data:
                break
            reviews.extend(page_data)
            if len(page_data) < per_page:
                break
            page += 1

        logger.debug(
            "Fetched %d reviews for PR %s/%s#%d", len(reviews), owner, repo, pr_number
        )
        return reviews

    @github_retry
    def get_commit_detail(
        self,
        owner: str,
        repo: str,
        sha: str,
    ) -> dict[str, Any]:
        """単一Commitの詳細を取得します（変更量メタ用）。

        Args:
            owner: リポジトリ所有者
            repo: リポジトリ名
            sha: Commit SHA

        Returns:
            Commit詳細を含む辞書

        Raises:
            requests.exceptions.HTTPError: API呼び出しが失敗した場合
        """
        logger.debug("Fetching commit detail: %s/%s@%s", owner, repo, sha)
        url = f"{self.base_url}/repos/{owner}/{repo}/commits/{sha}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_user_repositories(
        self,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> list[dict[str, Any]]:
        """ユーザーのRepository一覧を取得します（個人所有のみ）。

        Args:
            per_page: 1ページあたりのアイテム数

        Returns:
            Repository辞書のリスト（ownerがgithub_loginと一致するもののみ）

        Raises:
            requests.exceptions.HTTPError: API呼び出しが失敗した場合
        """
        logger.debug("Fetching user repositories for %s", self.github_login)

        repos: list[dict[str, Any]] = []
        page = 1

        while True:
            url = f"{self.base_url}/user/repos"
            params = {"per_page": per_page, "page": page}
            page_data = _get_json_with_retry(self.session, url, params)

            if not page_data:
                break

            # ownerが自分と一致するRepoのみフィルタ
            filtered = [
                repo
                for repo in page_data
                if repo.get("owner", {}).get("login") == self.github_login
            ]
            repos.extend(filtered)

            if len(page_data) < per_page:
                break
            page += 1

        logger.info(
            "Successfully fetched %d user repositories (filtered by owner=%s)",
            len(repos),
            self.github_login,
        )
        return repos

    def __enter__(self):
        """コンテキストマネージャーに入ります。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャーを抜けます。"""
        self.session.close()
        return False
