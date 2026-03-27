"""Browser history ingest API endpoint."""

import logging

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from pydantic import ValidationError

from backend.api.schemas.browser_history import (
    BrowserHistoryIngestRequest,
    BrowserHistoryIngestResponse,
)
from backend.config import BackendConfig
from backend.dependencies import get_config, verify_api_key
from backend.usecases.browser_history import (
    BrowserHistoryUseCaseError,
    compact_ingested_browser_history,
    ingest_browser_history,
)
from ingest.browser_history.schema import BrowserHistoryPayload

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/ingest/browser-history",
    tags=["ingest", "browser_history"],
)


def _trigger_browser_history_compaction(
    config: BackendConfig,
    compaction_targets: tuple[tuple[int, int], ...],
) -> None:
    """ingest 成功後に browser history compact を非同期で起動する。"""
    try:
        if config.r2 is None:
            logger.warning(
                "Skipping browser history compaction because R2 config is missing"
            )
            return
        compact_ingested_browser_history(config.r2, compaction_targets)
        logger.info(
            "Browser history compaction finished for targets=%s",
            list(compaction_targets),
        )
    except Exception:
        logger.exception(
            "Browser history compaction failed for targets=%s",
            list(compaction_targets),
        )


@router.post("", response_model=BrowserHistoryIngestResponse)
async def ingest_browser_history_endpoint(
    background_tasks: BackgroundTasks,
    request: dict = Body(...),
    config: BackendConfig = Depends(get_config),
    _: None = Depends(verify_api_key),
):
    """Browser history payload を受信して保存する。"""
    try:
        validated_request = BrowserHistoryIngestRequest.model_validate(request)
        payload = BrowserHistoryPayload.model_validate(
            validated_request.model_dump(mode="python")
        )
        result = ingest_browser_history(payload, config.r2)
        if result.compaction_targets:
            background_tasks.add_task(
                _trigger_browser_history_compaction,
                config,
                result.compaction_targets,
            )
        return BrowserHistoryIngestResponse(
            sync_id=result.sync_id,
            accepted=result.accepted,
            raw_saved=result.raw_saved,
            events_saved=result.events_saved,
            received_at=result.received_at,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BrowserHistoryUseCaseError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
