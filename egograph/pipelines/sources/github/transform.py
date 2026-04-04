"""GitHub生データを分析用スキーマに変換するモジュール."""

import hashlib
from datetime import datetime, timezone
from typing import Any


def _generate_pr_key(repo_full_name: str, pr_number: int) -> str:
    """PRのユニークキーを生成する。

    Args:
        repo_full_name: リポジトリのフルネーム (例: "owner/repo")
        pr_number: PR番号

    Returns:
        PRのユニークキー (ハッシュ値)
    """
    key_string = f"{repo_full_name}:{pr_number}"
    return hashlib.sha256(key_string.encode()).hexdigest()


def _generate_pr_event_id(
    repo_full_name: str,
    pr_number: int,
    updated_at_utc: str | None,
    state: str,
) -> str:
    key_string = f"{repo_full_name}:{pr_number}:{updated_at_utc or ''}:{state}"
    return hashlib.sha256(key_string.encode()).hexdigest()


def _is_personal_repo(repo: dict[str, Any], github_login: str) -> bool:
    """個人所有Repo判定。

    Args:
        repo: GitHub Repository APIレスポンス
        github_login: ユーザーのGitHubログイン名

    Returns:
        個人所有Repoの場合True、それ以外の場合False
    """
    owner = repo.get("owner", {})
    owner_login = owner.get("login")
    return owner_login == github_login


def _resolve_pr_action(pr: dict[str, Any]) -> str:
    merged_at = pr.get("merged_at")
    if merged_at:
        return "merged"

    state = pr.get("state", "open")
    if state == "closed":
        return "closed"

    closed_at = pr.get("closed_at")
    if state == "open" and closed_at:
        return "reopened"

    created_at = pr.get("created_at")
    updated_at = pr.get("updated_at")
    if created_at and updated_at and created_at != updated_at:
        return "updated"

    return "opened"


def transform_pull_request(
    pr: dict[str, Any], github_login: str
) -> dict[str, Any] | None:  # noqa: E501
    """GitHub PR APIレスポンスをPR現在状態スキーマに変換する。

    個人所有Repoでない場合はNoneを返す。

    Args:
        pr: GitHub PR APIレスポンス
        github_login: ユーザーのGitHubログイン名

    Returns:
        変換されたPR現在状態辞書、または個人所有でない場合はNone
    """
    # head.repoからrepo情報を取得
    head_info = pr.get("head", {})
    head_repo = head_info.get("repo", {})

    # 個人所有Repoでない場合はNone
    if not _is_personal_repo(head_repo, github_login):
        return None

    owner = head_repo.get("owner", {}).get("login", "")
    repo_name = head_repo.get("name", "")
    repo_full_name = head_repo.get("full_name", "")

    # labelsの抽出
    raw_labels = pr.get("labels", [])
    labels = [label.get("name") for label in raw_labels if label.get("name")]

    # merged情報
    merged_at = pr.get("merged_at")
    is_merged = merged_at is not None

    return {
        "pr_event_id": _generate_pr_event_id(
            repo_full_name,
            pr["number"],
            pr.get("updated_at"),
            pr.get("state", "open"),
        ),
        "pr_key": _generate_pr_key(repo_full_name, pr["number"]),
        "source": "github",
        "owner": owner,
        "repo": repo_name,
        "repo_full_name": repo_full_name,
        "pr_number": pr["number"],
        "pr_id": pr.get("id"),
        "action": _resolve_pr_action(pr),
        "state": pr.get("state", "open"),
        "is_merged": is_merged,
        "title": pr.get("title"),
        "labels": labels,
        "base_ref": pr.get("base", {}).get("ref"),
        "head_ref": head_info.get("ref"),
        "created_at_utc": pr.get("created_at"),
        "updated_at_utc": pr.get("updated_at"),
        "closed_at_utc": pr.get("closed_at"),
        "merged_at_utc": merged_at,
        "comments_count": pr.get("comments"),
        "review_comments_count": pr.get("review_comments"),
        "reviews_count": pr.get("reviews_count"),
        "commits_count": pr.get("commits"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files_count": pr.get("changed_files"),
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def transform_commit(
    commit: dict[str, Any], repo_full_name: str
) -> dict[str, Any] | None:  # noqa: E501
    """GitHub Commit APIレスポンスをCommitイベントスキーマに変換する。

    必須フィールド欠損時は該当フィールドをNullにして保存（他の有効フィールドは保持）。

    Args:
        commit: GitHub Commit APIレスポンス
        repo_full_name: リポジトリのフルネーム

    Returns:
        変換されたCommitイベント辞書、またはshaが欠損している場合はNone
    """
    sha = commit.get("sha")
    if not sha:
        return None

    # commit情報の抽出
    commit_info = commit.get("commit", {})

    # author情報の抽出
    author_info = commit_info.get("author", {})
    committed_date = author_info.get("date") if author_info else None

    # stats情報の抽出
    stats = commit.get("stats", {})
    files = commit.get("files")
    changed_files_count = len(files) if isinstance(files, list) else None

    # owner/repoの抽出
    parts = repo_full_name.split("/", 1) if repo_full_name else ["", ""]
    owner = parts[0] if len(parts) > 0 else ""
    repo = parts[1] if len(parts) > 1 else ""

    return {
        "commit_event_id": f"{repo_full_name}:{sha}",
        "source": "github",
        "owner": owner,
        "repo": repo,
        "repo_full_name": repo_full_name,
        "sha": sha,
        "message": commit_info.get("message"),
        "committed_at_utc": committed_date,
        "changed_files_count": changed_files_count,
        "additions": stats.get("additions"),
        "deletions": stats.get("deletions"),
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def transform_repository(
    repo: dict[str, Any], github_login: str
) -> dict[str, Any] | None:  # noqa: E501
    """GitHub Repository APIレスポンスをRepository Masterスキーマに変換する。

    個人所有Repoでない場合はNoneを返す。

    Args:
        repo: GitHub Repository APIレスポンス
        github_login: ユーザーのGitHubログイン名

    Returns:
        変換されたRepository辞書、または個人所有でない場合はNone
    """
    # 個人所有Repoでない場合はNone
    if not _is_personal_repo(repo, github_login):
        return None

    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    repo_full_name = repo.get("full_name", "")

    return {
        "repo_id": repo.get("id"),
        "source": "github",
        "owner": owner,
        "repo": repo_name,
        "repo_full_name": repo_full_name,
        "description": repo.get("description"),
        "homepage_url": repo.get("homepage"),
        "is_private": repo.get("private", False),
        "is_fork": repo.get("fork", False),
        "archived": repo.get("archived", False),
        "default_branch": repo.get("default_branch"),
        "primary_language": repo.get("language"),
        "topics": repo.get("topics", []),
        "stargazers_count": repo.get("stargazers_count"),
        "forks_count": repo.get("forks_count"),
        "open_issues_count": repo.get("open_issues_count"),
        "size_kb": repo.get("size"),
        "created_at_utc": repo.get("created_at"),
        "updated_at_utc": repo.get("updated_at"),
        "pushed_at_utc": repo.get("pushed_at"),
        "repo_summary_text": generate_repo_summary(repo),
        "summary_source": "template",
        "summary_updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def transform_prs_to_master(
    prs: list[dict[str, Any]], github_login: str
) -> list[dict[str, Any]]:  # noqa: E501
    """PRリストをマスター保存用スキーマに一括変換する。

    個人所有Repoのみ抽出し、他はスキップ。

    Args:
        prs: GitHub PR APIレスポンスのリスト
        github_login: ユーザーのGitHubログイン名

    Returns:
        変換されたPR現在状態辞書のリスト
    """
    results = []
    for pr in prs:
        transformed = transform_pull_request(pr, github_login)
        if transformed:
            results.append(transformed)
    return results


def transform_commits_to_events(
    commits: list[dict[str, Any]], repo_full_name: str
) -> list[dict[str, Any]]:  # noqa: E501
    """Commitリストをイベント保存用スキーマに一括変換する。

    必須フィールド欠損レコードは除外（全フィールド欠損の場合）。

    Args:
        commits: GitHub Commit APIレスポンスのリスト
        repo_full_name: リポジトリのフルネーム

    Returns:
        変換されたCommitイベント辞書のリスト
    """
    results = []
    for commit in commits:
        transformed = transform_commit(commit, repo_full_name)
        if transformed:
            results.append(transformed)
    return results


def generate_repo_summary(repo: dict[str, Any]) -> str:
    """Repositoryのdescriptionとtopicsから短文サマリーを生成する。

    MVP範囲: テンプレートベースの簡易生成。

    Args:
        repo: GitHub Repository APIレスポンス

    Returns:
        生成されたサマリー文字列
    """
    description = repo.get("description")
    topics = repo.get("topics", [])

    parts = []

    if description:
        parts.append(description)

    if topics:
        topics_str = ", ".join(topics[:5])  # 最大5つのトピック
        parts.append(f"Topics: {topics_str}")

    if not parts:
        return ""

    return " | ".join(parts)
