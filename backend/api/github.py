"""GitHub データアクセス API エンドポイント。

LLMを介さず、直接GitHub Worklogデータを取得するためのREST APIエンドポイントです。
ダッシュボードやデータ可視化などの用途に最適です。
"""

import logging
from datetime import date

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas import (
    ActivityStatsResponse,
    CommitResponse,
    PullRequestResponse,
    RepoSummaryStatsResponse,
    RepositoryResponse,
)
from backend.config import BackendConfig
from backend.constants import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
)
from backend.dependencies import get_config, get_db_connection, verify_api_key
from backend.infrastructure.database import (
    GitHubQueryParams,
    get_activity_stats,
    get_commits,
    get_pull_requests,
    get_repositories,
    get_repo_summary_stats,
)
from backend.validators import (
    validate_date_range,
    validate_granularity,
    validate_limit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/data/github", tags=["data", "github"])


@router.get("/pull-requests", response_model=list[PullRequestResponse])
async def get_pull_requests_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    owner: str | None = Query(None, description="フィルタ対象のオーナー"),
    repo: str | None = Query(None, description="フィルタ対象のリポジトリ"),
    state: str | None = Query(None, description="フィルタ対象の状態（open/closed）"),
    limit: int = Query(
        DEFAULT_LIMIT, ge=MIN_LIMIT, le=MAX_LIMIT, description="取得するPR数"
    ),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """指定期間のPull Requestイベントを取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        owner: フィルタ対象のオーナー（オプション）
        repo: フィルタ対象のリポジトリ（オプション）
        state: フィルタ対象の状態（オプション）
        limit: 取得するPR数（1-100）

    Returns:
        Pull Requestイベントのリスト

    Example:
        GET /v1/data/github/pull-requests?start_date=2024-01-01&end_date=2024-01-31&limit=5
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting pull requests: %s to %s, owner=%s, repo=%s, state=%s, limit=%s",
        start_date,
        end_date,
        owner,
        repo,
        state,
        limit,
    )
    params = GitHubQueryParams(
        conn=db_connection,
        bucket=config.r2.bucket_name,
        events_path=config.r2.events_path,
        master_path=config.r2.master_path,
        start_date=start,
        end_date=end,
    )
    return get_pull_requests(params, owner=owner, repo=repo, state=state, limit=validated_limit)


@router.get("/commits", response_model=list[CommitResponse])
async def get_commits_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    owner: str | None = Query(None, description="フィルタ対象のオーナー"),
    repo: str | None = Query(None, description="フィルタ対象のリポジトリ"),
    limit: int = Query(
        DEFAULT_LIMIT, ge=MIN_LIMIT, le=MAX_LIMIT, description="取得するCommit数"
    ),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """指定期間のCommitイベントを取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        owner: フィルタ対象のオーナー（オプション）
        repo: フィルタ対象のリポジトリ（オプション）
        limit: 取得するCommit数（1-100）

    Returns:
        Commitイベントのリスト

    Example:
        GET /v1/data/github/commits?start_date=2024-01-01&end_date=2024-01-31&limit=5
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting commits: %s to %s, owner=%s, repo=%s, limit=%s",
        start_date,
        end_date,
        owner,
        repo,
        limit,
    )
    params = GitHubQueryParams(
        conn=db_connection,
        bucket=config.r2.bucket_name,
        events_path=config.r2.events_path,
        master_path=config.r2.master_path,
        start_date=start,
        end_date=end,
    )
    return get_commits(params, owner=owner, repo=repo, limit=validated_limit)


@router.get("/repositories", response_model=list[RepositoryResponse])
async def get_repositories_endpoint(
    owner: str | None = Query(None, description="フィルタ対象のオーナー"),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """Repositoryマスターを取得します。

    Args:
        owner: フィルタ対象のオーナー（オプション）

    Returns:
        Repositoryリスト

    Example:
        GET /v1/data/github/repositories
    """
    logger.info("Getting repositories: owner=%s", owner)
    params = GitHubQueryParams(
        conn=db_connection,
        bucket=config.r2.bucket_name,
        events_path=config.r2.events_path,
        master_path=config.r2.master_path,
        start_date=date.min,
        end_date=date.max,
    )
    return get_repositories(params, owner=owner)


@router.get("/activity-stats", response_model=list[ActivityStatsResponse])
async def get_activity_stats_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    granularity: str = Query(
        "day", pattern="^(day|week|month)$", description="集計単位"
    ),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """期間別のアクティビティ統計を取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        granularity: 集計単位（"day", "week", "month"）

    Returns:
        期間別統計のリスト

    Example:
        GET /v1/data/github/activity-stats?start_date=2024-01-01&end_date=2024-01-31&granularity=week
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_granularity = validate_granularity(granularity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting activity stats: %s to %s, granularity=%s",
        start_date,
        end_date,
        granularity,
    )
    params = GitHubQueryParams(
        conn=db_connection,
        bucket=config.r2.bucket_name,
        events_path=config.r2.events_path,
        master_path=config.r2.master_path,
        start_date=start,
        end_date=end,
    )
    return get_activity_stats(params, granularity=validated_granularity)


@router.get("/repo-summary-stats", response_model=list[RepoSummaryStatsResponse])
async def get_repo_summary_stats_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    owner: str | None = Query(None, description="フィルタ対象のオーナー"),
    repo: str | None = Query(None, description="フィルタ対象のリポジトリ"),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """リポジトリ別のサマリー統計を取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        owner: フィルタ対象のオーナー（オプション）
        repo: フィルタ対象のリポジトリ（オプション）

    Returns:
        リポジトリ別統計のリスト

    Example:
        GET /v1/data/github/repo-summary-stats?start_date=2024-01-01&end_date=2024-01-31
    """
    try:
        start, end = validate_date_range(start_date, end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting repo summary stats: %s to %s, owner=%s, repo=%s",
        start_date,
        end_date,
        owner,
        repo,
    )
    params = GitHubQueryParams(
        conn=db_connection,
        bucket=config.r2.bucket_name,
        events_path=config.r2.events_path,
        master_path=config.r2.master_path,
        start_date=start,
        end_date=end,
    )
    return get_repo_summary_stats(params, owner=owner, repo_name=repo)
