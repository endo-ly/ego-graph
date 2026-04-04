"""GitHub API レスポンス用のテストフィクスチャ。"""

import copy
from typing import Any

# Repository モックレスポンス
MOCK_REPOSITORY_RESPONSE = {
    "id": 123456789,
    "name": "test-repo",
    "full_name": "test-user/test-repo",
    "owner": {
        "login": "test-user",
        "id": 12345,
        "type": "User",
    },
    "description": "Test repository",
    "homepage": "https://example.com",
    "private": False,
    "fork": False,
    "archived": False,
    "default_branch": "main",
    "language": "Python",
    "topics": ["testing", "github"],
    "stargazers_count": 10,
    "forks_count": 5,
    "open_issues_count": 2,
    "size": 1024,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-12-01T00:00:00Z",
    "pushed_at": "2024-12-01T00:00:00Z",
}

# Pull Request モックレスポンス
MOCK_PULL_REQUEST_RESPONSE = {
    "id": 987654321,
    "number": 1,
    "state": "open",
    "title": "Test PR",
    "body": "Test PR body",
    "user": {
        "login": "test-user",
        "id": 12345,
    },
    "base": {
        "ref": "main",
        "repo": {
            "full_name": "test-user/test-repo",
        },
    },
    "head": {
        "ref": "feature-branch",
        "repo": {
            "full_name": "test-user/test-repo",
        },
    },
    "labels": [
        {"name": "enhancement"},
        {"name": "testing"},
    ],
    "created_at": "2024-12-01T00:00:00Z",
    "updated_at": "2024-12-01T01:00:00Z",
    "closed_at": None,
    "merged_at": None,
    "merge_commit_sha": None,
    "comments": 3,
    "review_comments": 2,
    "commits": 5,
    "additions": 100,
    "deletions": 50,
    "changed_files": 3,
    "merged": False,
    "draft": False,
}

# PR Commits モックレスポンス
MOCK_PR_COMMITS_RESPONSE = [
    {
        "sha": "abc123def456",
        "commit": {
            "author": {
                "name": "Test User",
                "email": "test@example.com",
                "date": "2024-12-01T00:00:00Z",
            },
            "message": "Test commit message",
        },
        "author": {
            "login": "test-user",
            "id": 12345,
        },
    },
    {
        "sha": "def456ghi789",
        "commit": {
            "author": {
                "name": "Test User",
                "email": "test@example.com",
                "date": "2024-12-01T01:00:00Z",
            },
            "message": "Another test commit",
        },
        "author": {
            "login": "test-user",
            "id": 12345,
        },
    },
]

# Repository Commits モックレスポンス
MOCK_REPOSITORY_COMMITS_RESPONSE = [
    {
        "sha": "abc123def456",
        "commit": {
            "author": {
                "name": "Test User",
                "email": "test@example.com",
                "date": "2024-12-01T00:00:00Z",
            },
            "message": "Direct commit to main",
        },
        "author": {
            "login": "test-user",
            "id": 12345,
        },
    },
]

# PR Reviews モックレスポンス
MOCK_PR_REVIEWS_RESPONSE = [
    {
        "id": 111111,
        "user": {"login": "reviewer1", "id": 111},
        "state": "APPROVED",
        "submitted_at": "2024-12-01T02:00:00Z",
    },
    {
        "id": 222222,
        "user": {"login": "reviewer2", "id": 222},
        "state": "CHANGES_REQUESTED",
        "submitted_at": "2024-12-01T03:00:00Z",
    },
]

# Commit Detail モックレスポンス
MOCK_COMMIT_DETAIL_RESPONSE = {
    "sha": "abc123def456",
    "commit": {
        "author": {
            "name": "Test User",
            "email": "test@example.com",
            "date": "2024-12-01T00:00:00Z",
        },
        "message": "Test commit message",
    },
    "stats": {
        "additions": 50,
        "deletions": 20,
        "total": 70,
    },
    "files": [
        {"filename": "file1.py", "additions": 30, "deletions": 10, "changes": 40},
        {"filename": "file2.py", "additions": 20, "deletions": 10, "changes": 30},
    ],
    "author": {
        "login": "test-user",
        "id": 12345,
    },
}

# User Repositories モックレスポンス
MOCK_USER_REPOSITORIES_RESPONSE = [
    {
        "id": 123456789,
        "name": "test-repo",
        "full_name": "test-user/test-repo",
        "owner": {
            "login": "test-user",
            "id": 12345,
            "type": "User",
        },
        "private": False,
        "fork": False,
        "description": "Test repository",
        "homepage": "https://example.com",
        "language": "Python",
        "topics": ["testing"],
        "archived": False,
        "default_branch": "main",
        "stargazers_count": 10,
        "forks_count": 5,
        "open_issues_count": 2,
        "size": 1024,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-12-01T00:00:00Z",
        "pushed_at": "2024-12-01T00:00:00Z",
    },
    # 他ユーザーのRepo（フィルタ対象）
    {
        "id": 987654321,
        "name": "other-repo",
        "full_name": "other-user/other-repo",
        "owner": {
            "login": "other-user",
            "id": 54321,
            "type": "User",
        },
        "private": False,
        "fork": False,
        "description": "Other user repository",
        "homepage": None,
        "language": "JavaScript",
        "topics": [],
        "archived": False,
        "default_branch": "main",
        "stargazers_count": 5,
        "forks_count": 2,
        "open_issues_count": 1,
        "size": 512,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-12-01T00:00:00Z",
        "pushed_at": "2024-12-01T00:00:00Z",
    },
]


def get_mock_repository(
    owner: str = "test-user", repo: str = "test-repo"
) -> dict[str, Any]:  # noqa: E501
    """モックのRepositoryレスポンスを取得する。

    Args:
        owner: リポジトリ所有者
        repo: リポジトリ名

    Returns:
        モックデータを含む辞書
    """
    response = copy.deepcopy(MOCK_REPOSITORY_RESPONSE)
    response["name"] = repo
    response["full_name"] = f"{owner}/{repo}"
    response["owner"]["login"] = owner
    return response


def get_mock_pull_requests(count: int = 1) -> dict[str, Any] | list[dict[str, Any]]:
    """モックのPull Request一覧レスポンスを取得する。

    Args:
        count: 返す項目数

    Returns:
        モックデータを含む辞書または辞書リスト
    """
    if count == 1:
        return copy.deepcopy(MOCK_PULL_REQUEST_RESPONSE)
    return [copy.deepcopy(MOCK_PULL_REQUEST_RESPONSE) for _ in range(count)]


def get_mock_pr_commits(count: int = 2) -> list[dict[str, Any]]:
    """モックのPR Commitsレスポンスを取得する。

    Args:
        count: 返す項目数

    Returns:
        モックデータを含むリスト
    """
    return MOCK_PR_COMMITS_RESPONSE[:count]


def get_mock_repository_commits(count: int = 1) -> list[dict[str, Any]]:
    """モックのRepository Commitsレスポンスを取得する。

    Args:
        count: 返す項目数

    Returns:
        モックデータを含むリスト
    """
    return MOCK_REPOSITORY_COMMITS_RESPONSE[:count]


def get_mock_pr_reviews(count: int = 2) -> list[dict[str, Any]]:
    """モックのPR Reviewsレスポンスを取得する。

    Args:
        count: 返す項目数

    Returns:
        モックデータを含むリスト
    """
    return MOCK_PR_REVIEWS_RESPONSE[:count]


def get_mock_commit_detail() -> dict[str, Any]:
    """モックのCommit Detailレスポンスを取得する。

    Returns:
        モックデータを含む辞書
    """
    return MOCK_COMMIT_DETAIL_RESPONSE.copy()


def get_mock_user_repositories() -> list[dict[str, Any]]:
    """モックのUser Repositoriesレスポンスを取得する。

    Returns:
        モックデータを含むリスト
    """
    return [repo.copy() for repo in MOCK_USER_REPOSITORIES_RESPONSE]
