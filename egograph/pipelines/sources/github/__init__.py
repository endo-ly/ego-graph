"""GitHub source pipelines."""

from pipelines.sources.github.pipeline import run_github_compact, run_github_ingest

__all__ = [
    "run_github_compact",
    "run_github_ingest",
]
