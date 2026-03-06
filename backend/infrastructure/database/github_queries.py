"""GitHub データ用のSQLクエリテンプレートとヘルパー関数。"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

logger = logging.getLogger(__name__)


@dataclass
class GitHubQueryParams:
    """GitHubデータクエリ用の共通パラメータ。"""

    conn: duckdb.DuckDBPyConnection
    bucket: str
    events_path: str
    master_path: str
    start_date: date
    end_date: date


# Parquetパスパターン
GITHUB_PRS_PATH = "s3://{bucket}/{events_path}github/pull_requests/**/*.parquet"
GITHUB_PRS_PARTITION_PATH = "s3://{bucket}/{events_path}github/pull_requests/year={year}/month={month}/**/*.parquet"
GITHUB_COMMITS_PATH = "s3://{bucket}/{events_path}github/commits/**/*.parquet"
GITHUB_COMMITS_PARTITION_PATH = "s3://{bucket}/{events_path}github/commits/year={year}/month={month}/**/*.parquet"
GITHUB_REPOS_PATH = "s3://{bucket}/{master_path}github/repositories/**/*.parquet"


def get_prs_parquet_path(bucket: str, events_path: str) -> str:
    """GitHub PRイベントのS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        events_path: イベントデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/events/github/pull_requests/**/*.parquet）
    """
    return GITHUB_PRS_PATH.format(bucket=bucket, events_path=events_path)


def get_commits_parquet_path(bucket: str, events_path: str) -> str:
    """GitHub CommitイベントのS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        events_path: イベントデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/events/github/commits/**/*.parquet）
    """
    return GITHUB_COMMITS_PATH.format(bucket=bucket, events_path=events_path)


def get_repos_parquet_path(bucket: str, master_path: str) -> str:
    """GitHub RepositoryマスターのS3パスパターンを生成します。

    Args:
        bucket: R2バケット名
        master_path: マスターデータのパスプレフィックス

    Returns:
        S3パスパターン（例: s3://egograph/master/github/repositories/**/*.parquet）
    """
    return GITHUB_REPOS_PATH.format(bucket=bucket, master_path=master_path)


def _generate_pr_partition_paths(
    bucket: str, events_path: str, start_date: date, end_date: date
) -> list[str]:
    """指定期間の月パーティションに対応するPRイベントParquetパスリストを生成します。

    Args:
        bucket: R2バケット名
        events_path: イベントデータのパスプレフィックス
        start_date: 開始日
        end_date: 終了日

    Returns:
        月パーティションごとのS3パスリスト
    """
    paths: list[str] = []
    current = start_date.replace(day=1)
    end_month = end_date.replace(day=1)

    while current <= end_month:
        path = GITHUB_PRS_PARTITION_PATH.format(
            bucket=bucket,
            events_path=events_path,
            year=current.year,
            month=f"{current.month:02d}",
        )
        paths.append(path)

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    logger.debug(
        "Generated %d PR partition paths for period %s to %s",
        len(paths),
        start_date,
        end_date,
    )
    return paths


def _generate_commit_partition_paths(
    bucket: str, events_path: str, start_date: date, end_date: date
) -> list[str]:
    """指定期間の月パーティションに対応するCommitイベントParquetパスリストを生成します。

    Args:
        bucket: R2バケット名
        events_path: イベントデータのパスプレフィックス
        start_date: 開始日
        end_date: 終了日

    Returns:
        月パーティションごとのS3パスリスト
    """
    paths: list[str] = []
    current = start_date.replace(day=1)
    end_month = end_date.replace(day=1)

    while current <= end_month:
        path = GITHUB_COMMITS_PARTITION_PATH.format(
            bucket=bucket,
            events_path=events_path,
            year=current.year,
            month=f"{current.month:02d}",
        )
        paths.append(path)

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    logger.debug(
        "Generated %d commit partition paths for period %s to %s",
        len(paths),
        start_date,
        end_date,
    )
    return paths


def execute_query(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    """SQLクエリを実行し、結果を辞書のリストとして返します。

    Args:
        conn: DuckDBコネクション
        sql: 実行するSQLクエリ
        params: SQLパラメータ（オプション）

    Returns:
        クエリ結果（辞書のリスト）

    Raises:
        duckdb.Error: SQLクエリ実行に失敗した場合
    """
    result = conn.execute(sql, params or [])
    df = result.df()
    records = df.to_dict(orient="records")
    # numpy/pandas型をPython標準型に変換（JSONシリアライズ対応）
    return [
        {k: _convert_numpy_types(v) for k, v in record.items()}
        for record in records
    ]


def _convert_numpy_types(value: Any) -> Any:
    """numpy/pandas型をPython標準型に変換します。

    Args:
        value: 変換対象の値

    Returns:
        Python標準型に変換された値
    """
    import numpy as np

    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.int64, np.int32)):
        return int(value)
    if isinstance(value, (np.floating, np.float64, np.float32)):
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def get_pull_requests(
    params: GitHubQueryParams,
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
    partition_paths = _generate_pr_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

    query = """
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
            created_at_utc,
            updated_at_utc,
            closed_at_utc,
            merged_at_utc,
            additions,
            deletions,
            changed_files_count,
            reviews_count,
            commits_count
        FROM read_parquet(?)
        WHERE updated_at_utc::DATE BETWEEN ? AND ?
    """

    query_params: list[Any] = [partition_paths, params.start_date, params.end_date]

    if owner:
        query += " AND owner = ?"
        query_params.append(owner)

    if repo:
        query += " AND repo = ?"
        query_params.append(repo)

    if state:
        query += " AND state = ?"
        query_params.append(state)

    query += " ORDER BY updated_at_utc DESC"

    if limit is not None:
        query += f"\n        LIMIT {limit}"

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
    params: GitHubQueryParams,
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
    partition_paths = _generate_commit_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

    query = """
        SELECT
            commit_event_id,
            owner,
            repo,
            repo_full_name,
            sha,
            message,
            committed_at_utc,
            changed_files_count,
            additions,
            deletions
        FROM read_parquet(?)
        WHERE committed_at_utc::DATE BETWEEN ? AND ?
    """

    query_params: list[Any] = [partition_paths, params.start_date, params.end_date]

    if owner:
        query += " AND owner = ?"
        query_params.append(owner)

    if repo:
        query += " AND repo = ?"
        query_params.append(repo)

    query += " ORDER BY committed_at_utc DESC"

    if limit is not None:
        query += f"\n        LIMIT {limit}"

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
    params: GitHubQueryParams,
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
    repos_path = get_repos_parquet_path(params.bucket, params.master_path)

    query = """
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
            created_at_utc,
            updated_at_utc,
            pushed_at_utc,
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

    query += " ORDER BY updated_at_utc DESC"

    if limit:
        query += " LIMIT ?"
        query_params.append(limit)

    logger.debug("Executing get_repositories: owner=%s, repo=%s, limit=%s", owner, repo, limit)

    return execute_query(params.conn, query, query_params)


def get_activity_stats(
    params: GitHubQueryParams,
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
    pr_partition_paths = _generate_pr_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )
    commit_partition_paths = _generate_commit_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

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
                strftime(pr.updated_at_utc::DATE, '{date_format}') as period,
                pr.pr_key,
                MAX(CASE WHEN pr.action = 'opened' THEN 1 ELSE 0 END) as is_opened,
                MAX(CASE WHEN pr.action = 'merged' THEN 1 ELSE 0 END) as is_merged,
                COALESCE(MAX(pr.additions) FILTER (WHERE pr.action = 'merged'), 0) as additions,
                COALESCE(MAX(pr.deletions) FILTER (WHERE pr.action = 'merged'), 0) as deletions
            FROM read_parquet(?) pr
            WHERE pr.updated_at_utc::DATE BETWEEN ? AND ?
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
                strftime(c.committed_at_utc::DATE, '{date_format}') as period,
                COUNT(*) as commits_count,
                COALESCE(SUM(c.additions), 0) as commit_additions,
                COALESCE(SUM(c.deletions), 0) as commit_deletions
            FROM read_parquet(?) c
            WHERE c.committed_at_utc::DATE BETWEEN ? AND ?
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
            params.start_date,
            params.end_date,
            commit_partition_paths,
            params.start_date,
            params.end_date,
        ],
    )


def get_repo_summary_stats(
    params: GitHubQueryParams,
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
    pr_partition_paths = _generate_pr_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )
    commit_partition_paths = _generate_commit_partition_paths(
        params.bucket, params.events_path, params.start_date, params.end_date
    )

    query = """
        WITH pr_per_key AS (
            SELECT
                pr.owner,
                pr.repo,
                pr.repo_full_name,
                pr.pr_key,
                COALESCE(MAX(pr.additions) FILTER (WHERE pr.action = 'merged'), 0) as additions,
                COALESCE(MAX(pr.deletions) FILTER (WHERE pr.action = 'merged'), 0) as deletions,
                MAX(CASE WHEN pr.action = 'merged' THEN 1 ELSE 0 END) as is_merged
            FROM read_parquet(?) pr
            WHERE pr.updated_at_utc::DATE BETWEEN ? AND ?
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
            WHERE c.committed_at_utc::DATE BETWEEN ? AND ?
            GROUP BY c.owner, c.repo, c.repo_full_name
        )
        SELECT
            COALESCE(pr.owner, c.owner) as owner,
            COALESCE(pr.repo, c.repo) as repo,
            COALESCE(pr.repo_full_name, c.repo_full_name) as repo_full_name,
            COALESCE(pr.prs_total, 0) as prs_total,
            COALESCE(pr.prs_merged, 0) as prs_merged,
            COALESCE(c.commits_total, 0) as commits_total,
            COALESCE(pr.pr_additions, 0) + COALESCE(c.commit_additions, 0) as total_additions,
            COALESCE(pr.pr_deletions, 0) + COALESCE(c.commit_deletions, 0) as total_deletions,
            pr.last_pr_updated_at,
            c.last_commit_at
        FROM pr_summary pr
        FULL OUTER JOIN commit_summary c
            ON pr.owner = c.owner AND pr.repo = c.repo
    """

    query_params: list[Any] = [
        pr_partition_paths,
        params.start_date,
        params.end_date,
        commit_partition_paths,
        params.start_date,
        params.end_date,
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
