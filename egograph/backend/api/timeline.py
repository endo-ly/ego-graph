"""Daily Timeline REST API エンドポイント。

``GetDailyTimelineTool`` の validation と canonical response を利用し、
query parameter の受け取りと完全形の HTTP レスポンス生成を担う。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.schemas.timeline import DailyTimelineResponse
from backend.constants import (
    DEFAULT_GAP_MINUTES,
    DEFAULT_TIMELINE_LIMIT,
)
from backend.dependencies import get_daily_timeline_tool, verify_api_key_docs
from backend.domain.tools.timeline.daily import GetDailyTimelineTool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/data/timeline", tags=["data", "timeline"])


@router.get("/daily", response_model=DailyTimelineResponse)
async def get_daily_timeline_endpoint(
    date: str = Query(..., description="ローカル日付（YYYY-MM-DD）"),
    timezone: str | None = Query(None, description="IANA timezone"),
    sources: list[str] | None = Query(
        None, description="含めるデータソース（複数指定可）"
    ),
    gap_minutes: str | None = Query(
        str(DEFAULT_GAP_MINUTES),
        description="この分数以上の観測欠落を gaps に返す。0/null は検出なし",
    ),
    include_correlations: str = Query("true", description="関連候補を返すか"),
    include_raw_refs: str = Query("false", description="raw_ref を返すか"),
    limit: str = Query(str(DEFAULT_TIMELINE_LIMIT), description="items の最大件数"),
    tool: GetDailyTimelineTool = Depends(get_daily_timeline_tool),
    _api_key: None = Depends(verify_api_key_docs),
):
    """複数データソースを統合した1日分のタイムラインを取得する。"""
    try:
        return tool.execute(
            date=date,
            timezone=timezone,
            sources=sources,
            gap_minutes=gap_minutes,
            include_correlations=include_correlations,
            include_raw_refs=include_raw_refs,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
