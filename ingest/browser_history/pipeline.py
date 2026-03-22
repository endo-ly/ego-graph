"""Browser history ingestion pipeline."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from ingest.browser_history.schema import (
    BrowserHistoryIngestState,
    BrowserHistoryPayload,
)
from ingest.browser_history.storage import BrowserHistoryStorage
from ingest.browser_history.transform import transform_payload_to_event_rows


@dataclass(frozen=True)
class BrowserHistoryPipelineResult:
    """Browser history ingest 実行結果。"""

    sync_id: str
    accepted: int
    raw_saved: bool
    events_saved: bool
    received_at: datetime


def run_browser_history_pipeline(
    payload: BrowserHistoryPayload,
    storage: BrowserHistoryStorage,
    *,
    received_at: datetime | None = None,
) -> BrowserHistoryPipelineResult:
    """payload を raw/events/state へ保存する。"""
    normalized_received_at = received_at or datetime.now(timezone.utc)
    accepted = len(payload.items)

    raw_saved = False
    if payload.items:
        raw_key = storage.save_raw_json(
            payload.model_dump(mode="json"),
            browser=payload.browser,
            now=normalized_received_at,
        )
        if not raw_key:
            raise RuntimeError("Failed to save raw browser history payload")
        raw_saved = True

    rows = transform_payload_to_event_rows(payload, ingested_at=normalized_received_at)
    events_saved = False
    if rows:
        monthly_rows: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            visited_at = row["visited_at_utc"]
            monthly_rows[(visited_at.year, visited_at.month)].append(row)

        for (year, month), partition_rows in monthly_rows.items():
            saved_key = storage.save_parquet(partition_rows, year=year, month=month)
            if not saved_key:
                raise RuntimeError(
                    f"Failed to save browser history events for {year}-{month:02d}"
                )
        events_saved = True

    state = BrowserHistoryIngestState(
        sync_id=str(payload.sync_id),
        last_successful_sync_at=normalized_received_at,
        last_sync_status="events_saved",
        last_failure_code=None,
        last_received_at=normalized_received_at,
        last_accepted_count=accepted,
    )
    storage.save_state(
        state.model_dump(mode="json"),
        source_device=payload.source_device,
        browser=payload.browser,
        profile=payload.profile,
    )

    return BrowserHistoryPipelineResult(
        sync_id=str(payload.sync_id),
        accepted=accepted,
        raw_saved=raw_saved,
        events_saved=events_saved,
        received_at=normalized_received_at,
    )
