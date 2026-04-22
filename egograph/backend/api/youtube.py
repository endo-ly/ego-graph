"""YouTube data access API endpoints.

YouTube視聴イベントデータを直接取得するためのREST APIエンドポイントを提供します。
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas import (
    TopChannelResponse,
    TopVideoResponse,
    WatchEventResponse,
    WatchingStatsResponse,
)
from backend.config import BackendConfig
from backend.constants import (
    DEFAULT_TOP_TRACKS_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
)
from backend.dependencies import get_config
from backend.infrastructure.repositories.youtube_repository import YouTubeRepository
from backend.validators import (
    validate_date_range,
    validate_granularity,
    validate_limit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/data/youtube", tags=["data"])


@router.get("/watch-events", response_model=list[WatchEventResponse])
async def get_watch_events_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    limit: int | None = Query(
        None,
        ge=MIN_LIMIT,
        le=MAX_LIMIT,
        description="取得するイベント数",
    ),
    config: BackendConfig = Depends(get_config),
):
    """指定期間の視聴イベントを取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        limit: 取得するイベント数（1-100、省略時は全件）

    Returns:
        視聴イベントのリスト（視聴日時降順）

    Example:
        GET /v1/data/youtube/watch-events?start_date=2024-01-01&end_date=2024-01-31
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        if limit is not None:
            validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
        else:
            validated_limit = None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting YouTube watch events: %s to %s, limit=%s",
        start_date,
        end_date,
        limit,
    )

    repository = YouTubeRepository(config.r2)
    return repository.get_watch_events(start, end, validated_limit)


@router.get("/stats/watching", response_model=list[WatchingStatsResponse])
async def get_watching_stats_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    granularity: str = Query(
        "day", pattern="^(day|week|month)$", description="集計単位"
    ),
    config: BackendConfig = Depends(get_config),
):
    """期間別の視聴統計を取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        granularity: 集計単位（"day", "week", "month"）

    Returns:
        期間別統計のリスト

    Example:
        GET /v1/data/youtube/stats/watching?start_date=2024-01-01\\
            &end_date=2024-01-31&granularity=week
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_granularity = validate_granularity(granularity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting YouTube watching stats: %s to %s, granularity=%s",
        start_date,
        end_date,
        granularity,
    )

    repository = YouTubeRepository(config.r2)
    return repository.get_watching_stats(start, end, validated_granularity)


@router.get("/stats/top-videos", response_model=list[TopVideoResponse])
async def get_top_videos_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    limit: int = Query(
        DEFAULT_TOP_TRACKS_LIMIT,
        ge=MIN_LIMIT,
        le=MAX_LIMIT,
        description="取得する動画数",
    ),
    config: BackendConfig = Depends(get_config),
):
    """指定期間で最も視聴された動画を取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        limit: 取得する動画数（1-100）

    Returns:
        トップ動画のリスト（視聴イベント数降順）

    Example:
        GET /v1/data/youtube/stats/top-videos?start_date=2024-01-01\\
            &end_date=2024-01-31&limit=10
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting YouTube top videos: %s to %s, limit=%s",
        start_date,
        end_date,
        limit,
    )

    repository = YouTubeRepository(config.r2)
    return repository.get_top_videos(start, end, validated_limit)


@router.get("/stats/top-channels", response_model=list[TopChannelResponse])
async def get_top_channels_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    limit: int = Query(
        DEFAULT_TOP_TRACKS_LIMIT,
        ge=MIN_LIMIT,
        le=MAX_LIMIT,
        description="取得するチャンネル数",
    ),
    config: BackendConfig = Depends(get_config),
):
    """指定期間で最も視聴されたチャンネルを取得します。

    Args:
        start_date: 開始日
        end_date: 終了日
        limit: 取得するチャンネル数（1-100）

    Returns:
        トップチャンネルのリスト（視聴イベント数降順）

    Example:
        GET /v1/data/youtube/stats/top-channels?start_date=2024-01-01\\
            &end_date=2024-01-31&limit=10
    """
    try:
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit, max_value=MAX_LIMIT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    logger.info(
        "Getting YouTube top channels: %s to %s, limit=%s",
        start_date,
        end_date,
        limit,
    )

    repository = YouTubeRepository(config.r2)
    return repository.get_top_channels(start, end, validated_limit)
