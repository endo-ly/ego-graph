"""Browser history ingest/compact pipeline entrypoints."""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from pipelines.domain.workflow import WorkflowRun
from pipelines.sources.browser_history.compaction import compact_browser_history_targets
from pipelines.sources.browser_history.ingest_pipeline import (
    BrowserHistoryPipelineResult,
    run_browser_history_pipeline,
)
from pipelines.sources.browser_history.schema import BrowserHistoryPayload
from pipelines.sources.browser_history.storage import BrowserHistoryStorage
from pipelines.sources.common.compaction import resolve_target_months
from pipelines.sources.common.config import Config
from pipelines.sources.common.settings import PipelinesSettings

logger = logging.getLogger(__name__)

CompactionTarget = tuple[int, int]
CompactionEventEnqueuer = Callable[[Mapping[str, object]], str]

_BROWSER_HISTORY_COMPACT_WORKFLOW_ID = "browser_history_compact_workflow"


@dataclass(frozen=True)
class BrowserHistoryIngestResult:
    """Browser history ingest と compaction event enqueue の結果。"""

    sync_id: str
    accepted: int
    raw_saved: bool
    events_saved: bool
    received_at: datetime
    compaction_targets: tuple[CompactionTarget, ...]
    compact_run_id: str | None = None

    @classmethod
    def from_pipeline_result(
        cls,
        result: BrowserHistoryPipelineResult,
        *,
        compact_run_id: str | None = None,
    ) -> "BrowserHistoryIngestResult":
        """ingest 結果へ enqueue run id を付与して返す。"""
        return cls(
            sync_id=result.sync_id,
            accepted=result.accepted,
            raw_saved=result.raw_saved,
            events_saved=result.events_saved,
            received_at=result.received_at,
            compaction_targets=result.compaction_targets,
            compact_run_id=compact_run_id,
        )

    def to_summary_dict(self) -> dict[str, object]:
        """JSON serialize しやすい dict に変換する。"""
        summary = asdict(self)
        summary["received_at"] = self.received_at.isoformat()
        summary["compaction_targets"] = [
            {"year": year, "month": month} for year, month in self.compaction_targets
        ]
        return summary


def _resolve_browser_history_storage(
    config: Config | None,
    storage: BrowserHistoryStorage | None,
) -> BrowserHistoryStorage:
    if storage is not None:
        return storage

    resolved_config = config or PipelinesSettings.load()
    if not resolved_config.duckdb or not resolved_config.duckdb.r2:
        raise ValueError("R2 configuration is required for browser history pipeline")

    r2_conf = resolved_config.duckdb.r2
    return BrowserHistoryStorage(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
        bucket_name=r2_conf.bucket_name,
        raw_path=r2_conf.raw_path,
        events_path=r2_conf.events_path,
        master_path=r2_conf.master_path,
    )


def enqueue_browser_history_compaction_event(
    compaction_targets: Iterable[CompactionTarget],
    enqueue_run: CompactionEventEnqueuer,
    *,
    workflow_id: str = _BROWSER_HISTORY_COMPACT_WORKFLOW_ID,
) -> str | None:
    """compaction targets を event run として enqueue する。"""
    target_list = [{"year": year, "month": month} for year, month in compaction_targets]
    if not target_list:
        return None

    return enqueue_run(
        {
            "workflow_id": workflow_id,
            "trigger_type": "event",
            "queued_reason": "event_enqueue",
            "payload": {
                "compaction_targets": target_list,
            },
        }
    )


def run_browser_history_ingest(
    payload: BrowserHistoryPayload,
    *,
    config: Config | None = None,
    storage: BrowserHistoryStorage | None = None,
    received_at: datetime | None = None,
    enqueue_run: CompactionEventEnqueuer | None = None,
) -> BrowserHistoryIngestResult:
    """Browser History payload を保存し、必要なら compact event を enqueue する。"""
    resolved_storage = _resolve_browser_history_storage(config, storage)
    result = run_browser_history_pipeline(
        payload,
        resolved_storage,
        received_at=received_at or datetime.now(timezone.utc),
    )
    compact_run_id = None
    if enqueue_run is not None:
        compact_run_id = enqueue_browser_history_compaction_event(
            result.compaction_targets,
            enqueue_run,
        )
    return BrowserHistoryIngestResult.from_pipeline_result(
        result,
        compact_run_id=compact_run_id,
    )


def run_browser_history_compact(
    targets: Iterable[CompactionTarget],
    *,
    config: Config | None = None,
    storage: BrowserHistoryStorage | None = None,
) -> dict[str, object]:
    """指定月の Browser History compact を in-process で実行する。"""
    resolved_storage = _resolve_browser_history_storage(config, storage)
    target_tuple = tuple(sorted(set(targets)))
    compact_browser_history_targets(resolved_storage, target_tuple)
    return {
        "provider": "browser_history",
        "operation": "compact",
        "target_months": [f"{year}-{month:02d}" for year, month in target_tuple],
    }


def run_browser_history_compact_maintenance(
    *,
    config: Config | None = None,
    storage: BrowserHistoryStorage | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """前月+当月を対象に Browser History の補正 compact を実行する。"""
    targets = resolve_target_months(now=now)
    return run_browser_history_compact(
        targets,
        config=config,
        storage=storage,
    )


def compact_from_event_context(run: WorkflowRun) -> dict[str, object]:
    """event run の result_summary から対象月を取り出して compact する。"""
    raw_summary = run.result_summary or {}
    raw_targets = raw_summary.get("compaction_targets")
    targets = _parse_event_targets(raw_targets)
    if not targets:
        return {
            "provider": "browser_history",
            "operation": "compact",
            "target_months": [],
        }
    return run_browser_history_compact(targets)


def _parse_event_targets(raw_targets: Any) -> tuple[CompactionTarget, ...]:
    if not isinstance(raw_targets, list):
        return ()

    parsed_targets: list[CompactionTarget] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            continue
        year = item.get("year")
        month = item.get("month")
        if isinstance(year, int) and isinstance(month, int):
            parsed_targets.append((year, month))
    return tuple(parsed_targets)
