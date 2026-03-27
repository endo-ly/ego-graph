"""Browser history ingest package."""

from ingest.browser_history.compaction import compact_browser_history_targets
from ingest.browser_history.pipeline import (
    BrowserHistoryPipelineResult,
    run_browser_history_pipeline,
)

__all__ = [
    "compact_browser_history_targets",
    "BrowserHistoryPipelineResult",
    "run_browser_history_pipeline",
]
