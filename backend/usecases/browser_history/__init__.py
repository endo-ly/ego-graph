"""Browser history usecases."""

from backend.usecases.browser_history.ingest_browser_history import (
    BrowserHistoryUseCaseError,
    compact_ingested_browser_history,
    ingest_browser_history,
)

__all__ = [
    "BrowserHistoryUseCaseError",
    "compact_ingested_browser_history",
    "ingest_browser_history",
]
