"""Google Health分析データAPI。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas.google_health import (
    GoogleHealthColumnarResponse,
    GoogleHealthDailySummaryResponse,
    GoogleHealthRecordResponse,
    GoogleHealthTimeseriesResponse,
)
from backend.dependencies import (
    get_google_health_daily_metrics_use_case,
    get_google_health_daily_summary_use_case,
    get_google_health_record_use_case,
    get_google_health_sessions_use_case,
    get_google_health_timeseries_use_case,
)
from backend.usecases.google_health import (
    GetGoogleHealthDailyMetricsUseCase,
    GetGoogleHealthDailySummaryUseCase,
    GetGoogleHealthRecordUseCase,
    GetGoogleHealthSessionsUseCase,
    GetGoogleHealthTimeseriesUseCase,
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


@router.get(
    "/daily-metrics",
    response_model=GoogleHealthColumnarResponse,
)
def get_daily_metrics_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    data_type: str | None = Query(None, description="Google Health data type"),
    use_case: GetGoogleHealthDailyMetricsUseCase = Depends(
        get_google_health_daily_metrics_use_case
    ),
) -> dict:
    """日次Projectionをmetric単位で返す。"""
    try:
        return use_case.execute(start_date, end_date, data_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/timeseries",
    response_model=GoogleHealthTimeseriesResponse,
)
def get_timeseries_endpoint(
    data_type: str = Query(..., description="Google Health data type"),
    start_at: str = Query(..., description="開始日時（ISO-8601、timezone必須）"),
    end_at: str = Query(..., description="終了日時（ISO-8601、timezone必須）"),
    resolution: str = Query(
        "auto",
        description="解像度（auto/raw/5m/15m/30m/1h）",
    ),
    use_case: GetGoogleHealthTimeseriesUseCase = Depends(
        get_google_health_timeseries_use_case
    ),
) -> dict:
    """sample時系列を取得する。"""
    try:
        return use_case.execute(data_type, start_at, end_at, resolution)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/sessions",
    response_model=GoogleHealthColumnarResponse,
)
def get_sessions_endpoint(
    start_date: date = Query(..., description="開始日（YYYY-MM-DD）"),
    end_date: date = Query(..., description="終了日（YYYY-MM-DD）"),
    data_type: str | None = Query(None, description="sleepまたはexercise"),
    use_case: GetGoogleHealthSessionsUseCase = Depends(
        get_google_health_sessions_use_case
    ),
) -> dict:
    """sleep/exercise sessionを返す。"""
    try:
        return use_case.execute(start_date, end_date, data_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/records/{record_id}",
    response_model=GoogleHealthRecordResponse,
)
def get_record_endpoint(
    record_id: str,
    use_case: GetGoogleHealthRecordUseCase = Depends(get_google_health_record_use_case),
) -> dict:
    """完全保存recordをpayload付きで返す。"""
    try:
        return use_case.execute(record_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
