"""In-process YouTube derived pipeline entrypoint."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from pipelines.domain.workflow import WorkflowRun
from pipelines.sources.common.config import Config
from pipelines.sources.common.settings import PipelinesSettings
from pipelines.sources.youtube.api_client import YouTubeAPIClient
from pipelines.sources.youtube.extraction import (
    extract_youtube_watch_events,
    group_watch_events_by_month,
)
from pipelines.sources.youtube.metadata import (
    resolve_youtube_metadata,
    save_youtube_masters,
)
from pipelines.sources.youtube.storage import YouTubeStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YouTubeIngestRequest:
    """YouTube ingest 入力。"""

    sync_id: str
    target_months: tuple[tuple[int, int], ...]


def _resolve_storage(config: Config | None) -> YouTubeStorage:
    resolved_config = config or PipelinesSettings.load()
    if not resolved_config.duckdb or not resolved_config.duckdb.r2:
        raise ValueError("R2 configuration is required for youtube pipeline")

    r2_conf = resolved_config.duckdb.r2
    return YouTubeStorage(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
        bucket_name=r2_conf.bucket_name,
        events_path=r2_conf.events_path,
        master_path=r2_conf.master_path,
    )


def _resolve_api_client(config: Config | None) -> YouTubeAPIClient | None:
    resolved_config = config or PipelinesSettings.load()
    if not resolved_config.youtube:
        return None
    return YouTubeAPIClient(
        api_key=resolved_config.youtube.youtube_api_key.get_secret_value()
    )


def _parse_request(run: WorkflowRun) -> YouTubeIngestRequest | None:
    summary = run.result_summary or {}
    sync_id = summary.get("sync_id")
    raw_months = summary.get("target_months")
    if not isinstance(sync_id, str) or not sync_id.strip():
        return None
    if not isinstance(raw_months, list):
        return None

    target_months: list[tuple[int, int]] = []
    for item in raw_months:
        if not isinstance(item, dict):
            continue
        year = item.get("year")
        month = item.get("month")
        if (
            isinstance(year, int)
            and isinstance(month, int)
            and 1 <= year <= 9999
            and 1 <= month <= 12
        ):
            target_months.append((year, month))

    if not target_months:
        return None
    return YouTubeIngestRequest(
        sync_id=sync_id.strip(),
        target_months=tuple(target_months),
    )


def run_youtube_ingest(run: WorkflowRun) -> dict[str, object]:
    """browser_history を入力に YouTube watch events と master を更新する。"""
    request = _parse_request(run)
    if request is None:
        return {
            "provider": "youtube",
            "operation": "ingest",
            "status": "skipped",
            "reason": "missing_browser_history_event_context",
        }

    config = PipelinesSettings.load()
    storage = _resolve_storage(config)
    if storage.is_sync_processed(request.sync_id):
        return {
            "provider": "youtube",
            "operation": "ingest",
            "status": "skipped",
            "reason": "already_processed",
            "sync_id": request.sync_id,
        }

    page_views = storage.load_browser_history_page_views(
        sync_id=request.sync_id,
        target_months=request.target_months,
    )
    youtube_events = extract_youtube_watch_events(page_views)

    api_client = _resolve_api_client(config)
    video_master: list[dict] = []
    channel_master: list[dict] = []
    if youtube_events and api_client is not None:
        resolved = resolve_youtube_metadata(youtube_events, api_client)
        if resolved is not None:
            youtube_events, video_master, channel_master = resolved

    event_groups = group_watch_events_by_month(youtube_events)
    for (year, month), rows in event_groups.items():
        saved_key = storage.save_watch_events(
            rows,
            year=year,
            month=month,
            sync_id=request.sync_id,
        )
        if not saved_key:
            raise RuntimeError(
                f"Failed to save youtube watch events for {year}-{month:02d}"
            )

    if video_master:
        if not save_youtube_masters(
            storage,
            video_master,
            channel_master,
        ):
            raise RuntimeError("Failed to save youtube masters")

    storage.mark_sync_processed(
        request.sync_id,
        processed_at=datetime.now(timezone.utc),
        target_months=request.target_months,
        watch_event_count=len(youtube_events),
    )

    return {
        "provider": "youtube",
        "operation": "ingest",
        "status": "succeeded",
        "sync_id": request.sync_id,
        "watch_event_count": len(youtube_events),
        "target_months": [
            f"{year}-{month:02d}" for year, month in request.target_months
        ],
    }
