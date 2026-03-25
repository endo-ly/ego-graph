"""Browser History データアクセス API エンドポイント。"""

import logging
from datetime import date

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas import PageViewResponse, TopDomainResponse
from backend.config import BackendConfig
from backend.constants import (
    DEFAULT_PAGE_VIEWS_LIMIT,
    DEFAULT_TOP_DOMAINS_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
)
from backend.dependencies import get_config, get_db_connection, verify_api_key
from backend.infrastructure.database import (
    BrowserHistoryQueryParams,
    get_page_views,
    get_top_domains,
)
from backend.validators import validate_date_range, validate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/data/browser-history", tags=["data", "browser_history"])


def _build_query_params(
    db_connection: duckdb.DuckDBPyConnection,
    config: BackendConfig,
    start_date: date,
    end_date: date,
    limit: int,
) -> tuple[BrowserHistoryQueryParams, int]:
    """共通のクエリパラメータと limit を検証して構築する。"""
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    params = BrowserHistoryQueryParams(
        conn=db_connection,
        bucket=config.r2.bucket_name,
        events_path=config.r2.events_path,
        start_date=start,
        end_date=end,
        r2_config=config.r2,
    )
    return params, validated_limit


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
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """指定期間の page view 一覧を取得する。"""
    params, validated_limit = _build_query_params(
        db_connection,
        config,
        start_date,
        end_date,
        limit,
    )
    return get_page_views(
        params,
        browser=browser,
        profile=profile,
        limit=validated_limit,
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
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """指定期間の domain ランキングを取得する。"""
    params, validated_limit = _build_query_params(
        db_connection,
        config,
        start_date,
        end_date,
        limit,
    )
    return get_top_domains(
        params,
        browser=browser,
        profile=profile,
        limit=validated_limit,
    )
