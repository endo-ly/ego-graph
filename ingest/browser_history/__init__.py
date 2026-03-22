"""Browser history ingest package."""

from ingest.browser_history.pipeline import (
    BrowserHistoryPipelineResult,
    run_browser_history_pipeline,
)

__all__ = [
    "BrowserHistoryPipelineResult",
    "run_browser_history_pipeline",
]
