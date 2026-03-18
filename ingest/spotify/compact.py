"""Spotify compacted parquet generation."""

import argparse
import logging

from ingest.compaction import resolve_target_months
from ingest.settings import IngestSettings
from ingest.spotify.storage import SpotifyStorage

logger = logging.getLogger(__name__)


def _valid_month(value: str) -> int:
    month = int(value)
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError("month must be between 1 and 12")
    return month


def _validate_target_args(args: argparse.Namespace) -> None:
    if (args.year is None) != (args.month is None):
        raise SystemExit("Both --year and --month must be specified together")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=_valid_month, default=None)
    args = parser.parse_args()
    _validate_target_args(args)
    return args


def main() -> None:
    """Generate monthly compacted parquet files for Spotify datasets."""
    args = _parse_args()

    config = IngestSettings.load()
    if not config.duckdb or not config.duckdb.r2:
        raise ValueError("R2 configuration is required for compaction")

    r2_conf = config.duckdb.r2
    storage = SpotifyStorage(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
        bucket_name=r2_conf.bucket_name,
        raw_path=r2_conf.raw_path,
        events_path=r2_conf.events_path,
        master_path=r2_conf.master_path,
    )

    target_months = resolve_target_months(args.year, args.month)
    failures: list[str] = []
    for year, month in target_months:
        for data_domain, dataset_path, dedupe_key, sort_by in (
            ("events", "spotify/plays", "play_id", "played_at_utc"),
            ("master", "spotify/tracks", "track_id", "updated_at"),
            ("master", "spotify/artists", "artist_id", "updated_at"),
        ):
            try:
                storage.compact_month(
                    data_domain=data_domain,
                    dataset_path=dataset_path,
                    year=year,
                    month=month,
                    dedupe_key=dedupe_key,
                    sort_by=sort_by,
                )
            except Exception as exc:
                logger.exception(
                    "Spotify compaction failed: dataset=%s year=%d month=%02d error=%s",
                    dataset_path,
                    year,
                    month,
                    exc,
                )
                failures.append(f"{dataset_path}:{year}-{month:02d}")
    if failures:
        raise RuntimeError(f"Spotify compaction failed for: {', '.join(failures)}")
    logger.info("Spotify compaction finished for %s", target_months)


if __name__ == "__main__":
    main()
