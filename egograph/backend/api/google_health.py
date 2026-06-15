"""Google Health分析データAPI。"""

from datetime import date

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas.google_health import GoogleHealthDailySummaryResponse
from backend.dependencies import get_db_connection, get_google_health_repository
from backend.infrastructure.repositories.google_health_repository import (
    GoogleHealthRepository,
)
from backend.validators import validate_date_range

router = APIRouter(prefix="/v1/data/google-health", tags=["data"])


@router.get(
    "/daily-summary",
    response_model=list[GoogleHealthDailySummaryResponse],
)
def get_daily_summary_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    db_connection: duckdb.DuckDBPyConnection = Depends(get_db_connection),
    repository: GoogleHealthRepository = Depends(get_google_health_repository),
) -> list[dict]:
    """指定したローカル日付範囲の日次健康サマリを取得する。"""
    try:
        start, end = validate_date_range(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return repository.get_daily_summary(db_connection, start, end)
