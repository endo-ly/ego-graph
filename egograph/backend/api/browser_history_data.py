"""Browser History データアクセス API エンドポイント。"""

import logging
from datetime import date

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas import PageViewResponse, TopDomainResponse
from backend.constants import (
    DEFAULT_PAGE_VIEWS_LIMIT,
    DEFAULT_TOP_DOMAINS_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
)
from backend.dependencies import get_db_connection, get_browser_history_repository, verify_api_key_docs
from backend.infrastructure.repositories.browser_history_repository import (
    BrowserHistoryRepository,
)
from backend.validators import validate_date_range, validate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/data/browser-history", tags=["data", "browser_history"])


@router.get("/page-views", response_model=list[PageViewResponse])
def get_page_views_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    limit: int = Query(
        DEFAULT_PAGE_VIEWS_LIMIT,
        ge=MIN_LIMIT,
        le=MAX_LIMIT,
        description="取得件数",
    ),
    browser: str | None = Query(None, description="フィルタ対象のブラウザ"),
    profile: str | None = Query(None, description="フィルタ対象のプロファイル"),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    repository: BrowserHistoryRepository = Depends(get_browser_history_repository),
    _api_key: None = Depends(verify_api_key_docs),
):
    """指定期間の page view 一覧を取得する。"""
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return repository.get_page_views(
        db_connection, start, end, browser=browser, profile=profile, limit=validated_limit
    )


@router.get("/top-domains", response_model=list[TopDomainResponse])
def get_top_domains_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    limit: int = Query(
        DEFAULT_TOP_DOMAINS_LIMIT,
        ge=MIN_LIMIT,
        le=MAX_LIMIT,
        description="取得件数",
    ),
    browser: str | None = Query(None, description="フィルタ対象のブラウザ"),
    profile: str | None = Query(None, description="フィルタ対象のプロファイル"),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    repository: BrowserHistoryRepository = Depends(get_browser_history_repository),
    _api_key: None = Depends(verify_api_key_docs),
):
    """指定期間の domain ランキングを取得する。"""
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return repository.get_top_domains(
        db_connection, start, end, browser=browser, profile=profile, limit=validated_limit
    )
