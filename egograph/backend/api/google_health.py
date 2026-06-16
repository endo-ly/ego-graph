"""Google Health分析データAPI。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas.google_health import GoogleHealthDailySummaryResponse
from backend.dependencies import get_google_health_daily_summary_use_case
from backend.usecases.google_health import (
    GetGoogleHealthDailySummaryUseCase,
)

router = APIRouter(prefix="/v1/data/google-health", tags=["data"])


@router.get(
    "/daily-summary",
    response_model=list[GoogleHealthDailySummaryResponse],
)
def get_daily_summary_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    use_case: GetGoogleHealthDailySummaryUseCase = Depends(
        get_google_health_daily_summary_use_case
    ),
) -> list[dict]:
    """指定したローカル日付範囲の日次健康サマリを取得する。"""
    try:
        return use_case.execute(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
