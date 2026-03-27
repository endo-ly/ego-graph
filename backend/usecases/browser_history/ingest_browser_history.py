"""Browser history ingest usecase."""

import logging

from backend.config import R2Config
from ingest.browser_history.compaction import (
    CompactionTarget,
    compact_browser_history_targets,
)
from ingest.browser_history.pipeline import (
    BrowserHistoryPipelineResult,
    run_browser_history_pipeline,
)
from ingest.browser_history.schema import BrowserHistoryPayload
from ingest.browser_history.storage import BrowserHistoryStorage

logger = logging.getLogger(__name__)


class BrowserHistoryUseCaseError(Exception):
    """Browser history ingest usecase error."""


def build_browser_history_storage(r2_config: R2Config) -> BrowserHistoryStorage:
    """R2 config から BrowserHistoryStorage を生成する。"""
    return BrowserHistoryStorage(
        endpoint_url=r2_config.endpoint_url,
        access_key_id=r2_config.access_key_id,
        secret_access_key=r2_config.secret_access_key.get_secret_value(),
        bucket_name=r2_config.bucket_name,
        raw_path=r2_config.raw_path,
        events_path=r2_config.events_path,
        master_path=r2_config.master_path,
    )


def ingest_browser_history(
    payload: BrowserHistoryPayload,
    r2_config: R2Config,
) -> BrowserHistoryPipelineResult:
    """Browser history ingest を実行する。"""
    try:
        storage = build_browser_history_storage(r2_config)
        return run_browser_history_pipeline(payload, storage)
    except Exception as exc:
        raise BrowserHistoryUseCaseError(str(exc)) from exc


def compact_ingested_browser_history(
    r2_config: R2Config,
    targets: tuple[CompactionTarget, ...],
) -> None:
    """ingest 済み browser history の対象月を compact する。"""
    if not targets:
        logger.info(
            "Skipping browser history compaction because no targets were produced"
        )
        return

    storage = build_browser_history_storage(r2_config)
    compact_browser_history_targets(storage, targets)
