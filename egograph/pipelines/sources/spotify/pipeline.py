"""In-process Spotify pipeline entrypoints for workflow steps."""

import logging

from pipelines.sources.common.compaction import resolve_target_months
from pipelines.sources.common.config import Config
from pipelines.sources.common.settings import PipelinesSettings
from pipelines.sources.spotify.ingest_pipeline import (
    run_pipeline as _run_ingest_pipeline,
)
from pipelines.sources.spotify.storage import SpotifyStorage

logger = logging.getLogger(__name__)


def run_spotify_ingest(config: Config | None = None) -> dict[str, object]:
    """Spotify ingest を in-process で実行する。"""
    resolved_config = config or PipelinesSettings.load()
    _run_ingest_pipeline(resolved_config)
    return {"provider": "spotify", "operation": "ingest", "status": "succeeded"}


def run_spotify_compact(
    config: Config | None = None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, object]:
    """Spotify monthly compaction を in-process で実行する。"""
    resolved_config = config or PipelinesSettings.load()
    if not resolved_config.duckdb or not resolved_config.duckdb.r2:
        raise ValueError("R2 configuration is required for compaction")

    r2_conf = resolved_config.duckdb.r2
    storage = SpotifyStorage(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
        bucket_name=r2_conf.bucket_name,
        raw_path=r2_conf.raw_path,
        events_path=r2_conf.events_path,
        master_path=r2_conf.master_path,
    )

    target_months = resolve_target_months(year, month)
    compacted_keys: list[str] = []
    skipped_targets: list[str] = []
    failures: list[str] = []
    for target_year, target_month in target_months:
        for data_domain, dataset_path, dedupe_key, sort_by in (
            ("events", "spotify/plays", "play_id", "played_at_utc"),
            ("master", "spotify/tracks", "track_id", "updated_at"),
            ("master", "spotify/artists", "artist_id", "updated_at"),
        ):
            try:
                key = storage.compact_month(
                    data_domain=data_domain,
                    dataset_path=dataset_path,
                    year=target_year,
                    month=target_month,
                    dedupe_key=dedupe_key,
                    sort_by=sort_by,
                )
            except Exception:
                logger.exception(
                    "Spotify compaction failed: dataset=%s year=%d month=%02d",
                    dataset_path,
                    target_year,
                    target_month,
                )
                failures.append(f"{dataset_path}:{target_year}-{target_month:02d}")
                continue
            if key is None:
                skipped_targets.append(
                    f"{dataset_path}:{target_year}-{target_month:02d}"
                )
            else:
                compacted_keys.append(key)

    if failures:
        raise RuntimeError(f"Spotify compaction failed for: {', '.join(failures)}")

    return {
        "provider": "spotify",
        "operation": "compact",
        "target_months": [f"{y}-{m:02d}" for y, m in target_months],
        "compacted_keys": compacted_keys,
        "skipped_targets": skipped_targets,
    }
