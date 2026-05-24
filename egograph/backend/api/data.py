"""Direct data access API endpoints.

LLMを介さず、直接データを取得するための汎用REST APIエンドポイントです。
ダッシュボードやデータ可視化などの用途に最適です。
"""

import logging
from datetime import date

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas import ListeningStatsResponse, TopTrackResponse
from backend.constants import (
    DEFAULT_TOP_TRACKS_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
)
from backend.dependencies import (
    get_db_connection,
    get_spotify_repository,
    verify_api_key_docs,
)
from backend.infrastructure.repositories.spotify_repository import SpotifyRepository
from backend.validators import (
    validate_date_range,
    validate_granularity,
    validate_limit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/data/spotify", tags=["data"])


@router.get("/stats/top-tracks", response_model=list[TopTrackResponse])
async def get_top_tracks_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    limit: int = Query(
        DEFAULT_TOP_TRACKS_LIMIT, ge=MIN_LIMIT, le=MAX_LIMIT, description="取得する曲数"
    ),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    repository: SpotifyRepository = Depends(get_spotify_repository),
    _api_key: None = Depends(verify_api_key_docs),
):
    """指定期間で最も再生された曲を取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        limit: 取得する曲数（1-100）

    Returns:
        トップトラックのリスト

    Example:
        GET /v1/data/spotify/stats/top-tracks?start_date=2024-01-01&
            end_date=2024-01-31&limit=5
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info("Getting top tracks: %s to %s, limit=%s", start_date, end_date, limit)
    return repository.get_top_tracks(db_connection, start, end, validated_limit)


@router.get("/stats/listening", response_model=list[ListeningStatsResponse])
async def get_listening_stats_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    granularity: str = Query(
        "day", pattern="^(day|week|month)$", description="集計単位"
    ),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    repository: SpotifyRepository = Depends(get_spotify_repository),
    _api_key: None = Depends(verify_api_key_docs),
):
    """期間別の視聴統計を取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        granularity: 集計単位（"day", "week", "month"）

    Returns:
        期間別統計のリスト

    Example:
        GET /v1/data/spotify/stats/listening?start_date=2024-01-01&
            end_date=2024-01-31&granularity=week
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_granularity = validate_granularity(granularity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting listening stats: %s to %s, granularity=%s",
        start_date,
        end_date,
        granularity,
    )
    return repository.get_listening_stats(
        db_connection, start, end, validated_granularity
    )
