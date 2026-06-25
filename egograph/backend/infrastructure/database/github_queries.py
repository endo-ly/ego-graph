"""GitHub データ用のSQLクエリテンプレートとヘルパー関数。"""

import logging
from typing import Any

from dataset_catalog import datasets

from backend.infrastructure.database.parquet_paths import build_partition_paths
from backend.infrastructure.database.query_params import QueryParams, execute_query

logger = logging.getLogger(__name__)


def get_repos_parquet_path(bucket: str, master_path: str) -> str:
    """GitHub RepositoryマスターのS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        master_path: マスターデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/master/github/repositories/**/*.parquet）
    """
    return f"s3://{bucket}/{datasets.GITHUB_REPOSITORIES.source_glob(master_path)}"


def _resolve_pr_partition_paths(params: QueryParams) -> list[str]:
    return build_partition_paths(
        params.r2_config,
        datasets.GITHUB_PULL_REQUESTS,
        utc_start=params.utc_start,
        utc_end=params.utc_end,
    )


def _resolve_commit_partition_paths(params: QueryParams) -> list[str]:
    return build_partition_paths(
        params.r2_config,
        datasets.GITHUB_COMMITS,
        utc_start=params.utc_start,
        utc_end=params.utc_end,
    )


def get_pull_requests(
    params: QueryParams,
    owner: str | None = None,
    repo: str | None = None,
    state: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """指定期間のPull Requestイベントを取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        owner: フィルタ対象のオーナー（オプション）
        repo: フィルタ対象のリポジトリ（オプション）
        state: フィルタ対象の状態（open/closed、オプション）
        limit: 取得するPR数（デフォルト: None = 全件）

    Returns:
        PRイベントのリスト（updated_at_utc DESC）
        [
            {
                "pr_event_id": str,
                "pr_key": str,
                "owner": str,
                "repo": str,
                "repo_full_name": str,
                "pr_number": int,
                "action": str,
                "state": str,
                "is_merged": bool,
                "title": str,
                "labels": list[str],
                "created_at_utc": str,
                "updated_at_utc": str,
                "closed_at_utc": str | None,
                "merged_at_utc": str | None,
                "additions": int | None,
                "deletions": int | None,
                "changed_files_count": int | None,
                "reviews_count": int | None,
                "commits_count": int | None,
            },
            ...
        ]
    """
    partition_paths = _resolve_pr_partition_paths(params)

    query = f"""
        SELECT
            pr_event_id,
            pr_key,
            owner,
            repo,
            repo_full_name,
            pr_number,
            action,
            state,
            is_merged,
            title,
            labels,
            created_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS created_at,
            updated_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS updated_at,
            closed_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS closed_at,
            merged_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS merged_at,
            additions,
            deletions,
            changed_files_count,
            reviews_count,
            commits_count
        FROM read_parquet(?)
        WHERE updated_at_utc::TIMESTAMP >= ? AND updated_at_utc::TIMESTAMP < ?
    """

    query_params: list[Any] = [partition_paths, params.utc_start, params.utc_end]

    if owner:
        query += " AND owner = ?"
        query_params.append(owner)

    if repo:
        query += " AND repo = ?"
        query_params.append(repo)

    if state:
        query += " AND state = ?"
        query_params.append(state)

    query += " ORDER BY updated_at DESC"

    if limit is not None:
        query += "\n        LIMIT ?"
        query_params.append(limit)

    logger.debug(
        "Executing get_pull_requests: %s to %s, owner=%s, repo=%s, state=%s, limit=%s",
        params.start_date,
        params.end_date,
        owner,
        repo,
        state,
        limit,
    )

    return execute_query(params.conn, query, query_params)


def get_commits(
    params: QueryParams,
    owner: str | None = None,
    repo: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """指定期間のCommitイベントを取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        owner: フィルタ対象のオーナー（オプション）
        repo: フィルタ対象のリポジトリ（オプション）
        limit: 取得するCommit数（デフォルト: None = 全件）

    Returns:
        Commitイベントのリスト（committed_at_utc DESC）
        [
            {
                "commit_event_id": str,
                "owner": str,
                "repo": str,
                "repo_full_name": str,
                "sha": str,
                "message": str | None,
                "committed_at_utc": str,
                "changed_files_count": int | None,
                "additions": int | None,
                "deletions": int | None,
            },
            ...
        ]
    """
    partition_paths = _resolve_commit_partition_paths(params)

    query = f"""
        SELECT
            commit_event_id,
            owner,
            repo,
            repo_full_name,
            sha,
            message,
            committed_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS committed_at,
            changed_files_count,
            additions,
            deletions
        FROM read_parquet(?)
        WHERE committed_at_utc::TIMESTAMP >= ? AND committed_at_utc::TIMESTAMP < ?
    """

    query_params: list[Any] = [partition_paths, params.utc_start, params.utc_end]

    if owner:
        query += " AND owner = ?"
        query_params.append(owner)

    if repo:
        query += " AND repo = ?"
        query_params.append(repo)

    query += " ORDER BY committed_at DESC"

    if limit is not None:
        query += "\n        LIMIT ?"
        query_params.append(limit)

    logger.debug(
        "Executing get_commits: %s to %s, owner=%s, repo=%s, limit=%s",
        params.start_date,
        params.end_date,
        owner,
        repo,
        limit,
    )

    return execute_query(params.conn, query, query_params)


def get_repositories(
    params: QueryParams,
    owner: str | None = None,
    repo: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Repositoryマスターを取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス）
        owner: フィルタ対象のオーナー（オプション）
        repo: フィルタ対象のリポジトリ（オプション）
        limit: 取得件数上限（オプション）

    Returns:
        Repositoryリスト
        [
            {
                "repo_id": int,
                "owner": str,
                "repo": str,
                "repo_full_name": str,
                "description": str | None,
                "is_private": bool,
                "is_fork": bool,
                "archived": bool,
                "primary_language": str | None,
                "topics": list[str],
                "stargazers_count": int | None,
                "forks_count": int | None,
                "open_issues_count": int | None,
                "size_kb": int | None,
                "created_at_utc": str,
                "updated_at_utc": str,
                "pushed_at_utc": str | None,
                "repo_summary_text": str | None,
                "summary_source": str | None,
            },
            ...
        ]
    """
    repos_path = get_repos_parquet_path(
        params.r2_config.bucket_name, params.r2_config.master_path
    )

    query = f"""
        SELECT
            repo_id,
            owner,
            repo,
            repo_full_name,
            description,
            is_private,
            is_fork,
            archived,
            primary_language,
            topics,
            stargazers_count,
            forks_count,
            open_issues_count,
            size_kb,
            created_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS created_at,
            updated_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS updated_at,
            pushed_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS pushed_at,
            repo_summary_text,
            summary_source
        FROM read_parquet(?, union_by_name=True)
    """

    query_params: list[Any] = [repos_path]

    where_conditions: list[str] = []
    if owner:
        where_conditions.append("owner = ?")
        query_params.append(owner)
    if repo:
        where_conditions.append("repo = ?")
        query_params.append(repo)

    if where_conditions:
        query += " WHERE " + " AND ".join(where_conditions)

    query += " ORDER BY updated_at DESC"

    if limit:
        query += " LIMIT ?"
        query_params.append(limit)

    logger.debug(
        "Executing get_repositories: owner=%s, repo=%s, limit=%s",
        owner,
        repo,
        limit,
    )

    return execute_query(params.conn, query, query_params)


def get_activity_stats(
    params: QueryParams,
    granularity: str = "day",
) -> list[dict[str, Any]]:
    """期間別のアクティビティ統計を取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        granularity: 集計単位（"day", "week", "month"）

    Returns:
        期間別統計のリスト
        [
            {
                "period": str,
                "prs_created": int,
                "prs_merged": int,
                "commits_count": int,
                "additions": int,
                "deletions": int,
            },
            ...
        ]

    Raises:
        ValueError: granularityが無効な場合
    """
    pr_partition_paths = _resolve_pr_partition_paths(params)
    commit_partition_paths = _resolve_commit_partition_paths(params)

    date_format_map = {
        "day": "%Y-%m-%d",
        "week": "%G-W%V",
        "month": "%Y-%m",
    }

    if granularity not in date_format_map:
        allowed = list(date_format_map.keys())
        raise ValueError(
            f"Invalid granularity: {granularity}. Must be one of {allowed}"
        )

    date_format = date_format_map[granularity]

    query = f"""
        WITH pr_per_key AS (
            SELECT
                strftime(
                    pr.updated_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                    AT TIME ZONE '{params.tz_name}',
                    '{date_format}'
                ) as period,
                pr.pr_key,
                MAX(CASE WHEN pr.action = 'opened' THEN 1 ELSE 0 END) as is_opened,
                MAX(CASE WHEN pr.action = 'merged' THEN 1 ELSE 0 END) as is_merged,
                COALESCE(
                    MAX(pr.additions) FILTER (WHERE pr.action = 'merged'),
                    0
                ) as additions,
                COALESCE(
                    MAX(pr.deletions) FILTER (WHERE pr.action = 'merged'),
                    0
                ) as deletions
            FROM read_parquet(?) pr
            WHERE pr.updated_at_utc::TIMESTAMP >= ? AND pr.updated_at_utc::TIMESTAMP < ?
            GROUP BY period, pr.pr_key
        ),
        pr_stats AS (
            SELECT
                period,
                SUM(is_opened) as prs_created,
                SUM(is_merged) as prs_merged,
                COALESCE(SUM(additions), 0) as pr_additions,
                COALESCE(SUM(deletions), 0) as pr_deletions
            FROM pr_per_key
            GROUP BY period
        ),
        commit_stats AS (
            SELECT
                strftime(
                    c.committed_at_utc::TIMESTAMP AT TIME ZONE 'UTC'
                    AT TIME ZONE '{params.tz_name}',
                    '{date_format}'
                ) as period,
                COUNT(*) as commits_count,
                COALESCE(SUM(c.additions), 0) as commit_additions,
                COALESCE(SUM(c.deletions), 0) as commit_deletions
            FROM read_parquet(?) c
            WHERE c.committed_at_utc::TIMESTAMP >= ?
              AND c.committed_at_utc::TIMESTAMP < ?
            GROUP BY period
        )
        SELECT
            COALESCE(pr.period, c.period) as period,
            COALESCE(pr.prs_created, 0) as prs_created,
            COALESCE(pr.prs_merged, 0) as prs_merged,
            COALESCE(c.commits_count, 0) as commits_count,
            COALESCE(pr.pr_additions, 0) + COALESCE(c.commit_additions, 0) as additions,
            COALESCE(pr.pr_deletions, 0) + COALESCE(c.commit_deletions, 0) as deletions
        FROM pr_stats pr
        FULL OUTER JOIN commit_stats c ON pr.period = c.period
        ORDER BY period ASC
    """

    logger.debug(
        "Executing get_activity_stats: %s to %s, granularity=%s",
        params.start_date,
        params.end_date,
        granularity,
    )

    return execute_query(
        params.conn,
        query,
        [
            pr_partition_paths,
            params.utc_start,
            params.utc_end,
            commit_partition_paths,
            params.utc_start,
            params.utc_end,
        ],
    )


def get_repo_summary_stats(
    params: QueryParams,
    owner: str | None = None,
    repo_name: str | None = None,
) -> list[dict[str, Any]]:
    """リポジトリ別のサマリー統計を取得します。

    Args:
        params: クエリパラメータ（コネクション、バケット、パス、日付範囲）
        owner: フィルタ対象のオーナー（オプション）
        repo_name: フィルタ対象のリポジトリ名（オプション）

    Returns:
        リポジトリ別統計のリスト
        [
            {
                "owner": str,
                "repo": str,
                "repo_full_name": str,
                "prs_total": int,
                "prs_merged": int,
                "commits_total": int,
                "total_additions": int,
                "total_deletions": int,
                "last_pr_updated_at": str | None,
                "last_commit_at": str | None,
            },
            ...
        ]
    """
    pr_partition_paths = _resolve_pr_partition_paths(params)
    commit_partition_paths = _resolve_commit_partition_paths(params)

    query = f"""
        WITH pr_per_key AS (
            SELECT
                pr.owner,
                pr.repo,
                pr.repo_full_name,
                pr.pr_key,
                COALESCE(
                    MAX(pr.additions) FILTER (WHERE pr.action = 'merged'),
                    0
                ) as additions,
                COALESCE(
                    MAX(pr.deletions) FILTER (WHERE pr.action = 'merged'),
                    0
                ) as deletions,
                MAX(CASE WHEN pr.action = 'merged' THEN 1 ELSE 0 END) as is_merged
            FROM read_parquet(?) pr
            WHERE pr.updated_at_utc::TIMESTAMP >= ? AND pr.updated_at_utc::TIMESTAMP < ?
            GROUP BY pr.owner, pr.repo, pr.repo_full_name, pr.pr_key
        ),
        pr_summary AS (
            SELECT
                owner,
                repo,
                repo_full_name,
                COUNT(*) as prs_total,
                SUM(is_merged) as prs_merged,
                COALESCE(SUM(additions), 0) as pr_additions,
                COALESCE(SUM(deletions), 0) as pr_deletions,
                NULL as last_pr_updated_at
            FROM pr_per_key
            GROUP BY owner, repo, repo_full_name
        ),
        commit_summary AS (
            SELECT
                c.owner,
                c.repo,
                c.repo_full_name,
                COUNT(*) as commits_total,
                COALESCE(SUM(c.additions), 0) as commit_additions,
                COALESCE(SUM(c.deletions), 0) as commit_deletions,
                MAX(c.committed_at_utc) as last_commit_at
            FROM read_parquet(?) c
            WHERE c.committed_at_utc::TIMESTAMP >= ?
              AND c.committed_at_utc::TIMESTAMP < ?
            GROUP BY c.owner, c.repo, c.repo_full_name
        )
        SELECT
            COALESCE(pr.owner, c.owner) as owner,
            COALESCE(pr.repo, c.repo) as repo,
            COALESCE(pr.repo_full_name, c.repo_full_name) as repo_full_name,
            COALESCE(pr.prs_total, 0) as prs_total,
            COALESCE(pr.prs_merged, 0) as prs_merged,
            COALESCE(c.commits_total, 0) as commits_total,
            COALESCE(pr.pr_additions, 0) + COALESCE(c.commit_additions, 0)
                as total_additions,
            COALESCE(pr.pr_deletions, 0) + COALESCE(c.commit_deletions, 0)
                as total_deletions,
            pr.last_pr_updated_at,
            c.last_commit_at::TIMESTAMP AT TIME ZONE 'UTC'
                AT TIME ZONE '{params.tz_name}' AS last_commit_at
        FROM pr_summary pr
        FULL OUTER JOIN commit_summary c
            ON pr.owner = c.owner AND pr.repo = c.repo
    """

    query_params: list[Any] = [
        pr_partition_paths,
        params.utc_start,
        params.utc_end,
        commit_partition_paths,
        params.utc_start,
        params.utc_end,
    ]

    if owner:
        query += " WHERE (COALESCE(pr.owner, c.owner) = ?)"
        query_params.append(owner)

    if repo_name:
        if owner:
            query += " AND (COALESCE(pr.repo, c.repo) = ?)"
        else:
            query += " WHERE (COALESCE(pr.repo, c.repo) = ?)"
        query_params.append(repo_name)

    query += " ORDER BY total_additions + total_deletions DESC"

    logger.debug(
        "Executing get_repo_summary_stats: %s to %s, owner=%s, repo=%s",
        params.start_date,
        params.end_date,
        owner,
        repo_name,
    )

    return execute_query(params.conn, query, query_params)
