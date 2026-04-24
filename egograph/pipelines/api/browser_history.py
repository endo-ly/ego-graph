"""Browser History ingest API."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from pipelines.api.dependencies import get_service, verify_api_key
from pipelines.service import PipelineService
from pipelines.sources.browser_history.pipeline import (
    BrowserHistoryPayload,
    run_browser_history_ingest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/ingest/browser-history",
    tags=["ingest", "browser_history"],
)


@router.post("", status_code=202)
def ingest_browser_history_endpoint(
    payload: dict,
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> dict:
    """Browser History payload を保存し、YouTube ingest run を enqueue する。"""
    try:
        validated_payload = BrowserHistoryPayload.model_validate(payload)
        result = run_browser_history_ingest(validated_payload)
        youtube_run = None
        if result.compaction_targets:
            try:
                youtube_run = service.enqueue_youtube_ingest(
                    sync_id=result.sync_id,
                    target_months=list(result.compaction_targets),
                    requested_by="api",
                )
            except Exception:
                logger.exception(
                    "Failed to enqueue youtube ingest for sync_id=%s",
                    result.sync_id,
                )
                youtube_run = None
        return {
            "sync_id": result.sync_id,
            "accepted": result.accepted,
            "raw_saved": result.raw_saved,
            "events_saved": result.events_saved,
            "received_at": result.received_at,
            "youtube_run_id": youtube_run.run_id if youtube_run else None,
        }
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
