"""Spotify source pipelines."""

from pipelines.sources.spotify.pipeline import (
    run_spotify_compact,
    run_spotify_ingest,
)

__all__ = [
    "run_spotify_compact",
    "run_spotify_ingest",
]
