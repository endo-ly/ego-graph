"""Bootstrap compacted parquet generation for all workflow-managed providers."""

import argparse
import logging
from typing import Any

import boto3
from dataset_catalog import DatasetDefinition, datasets, monthly_compaction_datasets

from pipelines.sources.browser_history.storage import BrowserHistoryStorage
from pipelines.sources.common.compaction import discover_available_months
from pipelines.sources.common.settings import PipelinesSettings
from pipelines.sources.github.storage import GitHubWorklogStorage
from pipelines.sources.spotify.storage import SpotifyStorage
from pipelines.sources.youtube.storage import YouTubeStorage

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider",
        choices=("all", "spotify", "github", "browser_history", "youtube"),
        default="all",
        help="Compact only the selected provider (default: all).",
    )
    return parser.parse_args()


def _build_s3_client(
    endpoint_url: str,
    access_key_id: str,
    secret_access_key: str,
) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def _discover_dataset_months(
    s3_client: Any,
    bucket_name: str,
    root_prefix: str,
    dataset: DatasetDefinition,
) -> list[tuple[int, int]]:
    source_prefix = dataset.source_prefix(root_prefix)
    return discover_available_months(s3_client, bucket_name, source_prefix)


def _compact_spotify(
    s3_client: Any,
    bucket_name: str,
    events_path: str,
    master_path: str,
    storage: SpotifyStorage,
) -> list[str]:
    failures: list[str] = []

    for dataset in monthly_compaction_datasets("spotify"):
        root_prefix = events_path if dataset.domain.value == "events" else master_path
        months = _discover_dataset_months(
            s3_client,
            bucket_name,
            root_prefix,
            dataset,
        )
        logger.info(
            "Bootstrap compact target months discovered: "
            "provider=spotify dataset=%s months=%s",
            dataset.path,
            months,
        )
        for year, month in months:
            try:
                storage.compact_month(
                    dataset=dataset,
                    year=year,
                    month=month,
                )
            except Exception as exc:
                logger.exception(
                    "Bootstrap Spotify compaction failed: "
                    "dataset=%s year=%d month=%02d error=%s",
                    dataset.path,
                    year,
                    month,
                    exc,
                )
                failures.append(f"spotify:{dataset.path}:{year}-{month:02d}")

    return failures


def _compact_github(
    s3_client: Any,
    bucket_name: str,
    events_path: str,
    storage: GitHubWorklogStorage,
) -> list[str]:
    failures: list[str] = []

    for dataset in monthly_compaction_datasets("github"):
        months = _discover_dataset_months(
            s3_client,
            bucket_name,
            events_path,
            dataset,
        )
        logger.info(
            "Bootstrap compact target months discovered: "
            "provider=github dataset=%s months=%s",
            dataset.path,
            months,
        )
        for year, month in months:
            try:
                storage.compact_month(
                    dataset=dataset,
                    year=year,
                    month=month,
                )
            except Exception as exc:
                logger.exception(
                    "Bootstrap GitHub compaction failed: "
                    "dataset=%s year=%d month=%02d error=%s",
                    dataset.path,
                    year,
                    month,
                    exc,
                )
                failures.append(f"github:{dataset.path}:{year}-{month:02d}")

    return failures


def _compact_browser_history(
    s3_client: Any,
    bucket_name: str,
    events_path: str,
    storage: BrowserHistoryStorage,
) -> list[str]:
    failures: list[str] = []
    dataset = datasets.BROWSER_HISTORY_PAGE_VIEWS

    months = _discover_dataset_months(
        s3_client,
        bucket_name,
        events_path,
        dataset,
    )
    logger.info(
        "Bootstrap compact target months discovered: "
        "provider=browser_history dataset=%s months=%s",
        dataset.path,
        months,
    )
    for year, month in months:
        try:
            storage.compact_month(
                year=year,
                month=month,
            )
        except Exception as exc:
            logger.exception(
                "Bootstrap browser_history compaction failed: "
                "dataset=%s year=%d month=%02d error=%s",
                dataset.path,
                year,
                month,
                exc,
            )
            failures.append(f"browser_history:{dataset.path}:{year}-{month:02d}")

    return failures


def _compact_youtube(
    s3_client: Any,
    bucket_name: str,
    events_path: str,
    storage: YouTubeStorage,
) -> list[str]:
    failures: list[str] = []
    dataset = datasets.YOUTUBE_WATCH_EVENTS

    months = _discover_dataset_months(
        s3_client,
        bucket_name,
        events_path,
        dataset,
    )
    logger.info(
        "Bootstrap compact target months discovered: "
        "provider=youtube dataset=%s months=%s",
        dataset.path,
        months,
    )
    for year, month in months:
        try:
            key = storage.compact_month(year=year, month=month)
            if key is None:
                logger.info(
                    "Bootstrap YouTube compaction skipped (no data): "
                    "year=%d month=%02d",
                    year,
                    month,
                )
        except Exception as exc:
            logger.exception(
                "Bootstrap YouTube compaction failed: "
                "dataset=%s year=%d month=%02d error=%s",
                dataset.path,
                year,
                month,
                exc,
            )
            failures.append(f"youtube:{dataset.path}:{year}-{month:02d}")

    return failures


def main() -> None:
    """Bootstrap compacted parquet generation for all configured providers."""
    args = _parse_args()
    config = PipelinesSettings.load()
    if not config.duckdb or not config.duckdb.r2:
        raise ValueError("R2 configuration is required for bootstrap compaction")

    r2_conf = config.duckdb.r2
    s3_client = _build_s3_client(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
    )

    failures: list[str] = []

    if args.provider in ("all", "spotify"):
        spotify_storage = SpotifyStorage(
            endpoint_url=r2_conf.endpoint_url,
            access_key_id=r2_conf.access_key_id,
            secret_access_key=r2_conf.secret_access_key.get_secret_value(),
            bucket_name=r2_conf.bucket_name,
            raw_path=r2_conf.raw_path,
            events_path=r2_conf.events_path,
            master_path=r2_conf.master_path,
        )
        failures.extend(
            _compact_spotify(
                s3_client=s3_client,
                bucket_name=r2_conf.bucket_name,
                events_path=r2_conf.events_path,
                master_path=r2_conf.master_path,
                storage=spotify_storage,
            )
        )

    if args.provider in ("all", "github"):
        github_storage = GitHubWorklogStorage(
            endpoint_url=r2_conf.endpoint_url,
            access_key_id=r2_conf.access_key_id,
            secret_access_key=r2_conf.secret_access_key.get_secret_value(),
            bucket_name=r2_conf.bucket_name,
            raw_path=r2_conf.raw_path,
            events_path=r2_conf.events_path,
            master_path=r2_conf.master_path,
        )
        failures.extend(
            _compact_github(
                s3_client=s3_client,
                bucket_name=r2_conf.bucket_name,
                events_path=r2_conf.events_path,
                storage=github_storage,
            )
        )

    if args.provider in ("all", "browser_history"):
        browser_history_storage = BrowserHistoryStorage(
            endpoint_url=r2_conf.endpoint_url,
            access_key_id=r2_conf.access_key_id,
            secret_access_key=r2_conf.secret_access_key.get_secret_value(),
            bucket_name=r2_conf.bucket_name,
            raw_path=r2_conf.raw_path,
            events_path=r2_conf.events_path,
            master_path=r2_conf.master_path,
        )
        failures.extend(
            _compact_browser_history(
                s3_client=s3_client,
                bucket_name=r2_conf.bucket_name,
                events_path=r2_conf.events_path,
                storage=browser_history_storage,
            )
        )

    if args.provider in ("all", "youtube"):
        youtube_storage = YouTubeStorage(
            endpoint_url=r2_conf.endpoint_url,
            access_key_id=r2_conf.access_key_id,
            secret_access_key=r2_conf.secret_access_key.get_secret_value(),
            bucket_name=r2_conf.bucket_name,
            events_path=r2_conf.events_path,
            master_path=r2_conf.master_path,
        )
        failures.extend(
            _compact_youtube(
                s3_client=s3_client,
                bucket_name=r2_conf.bucket_name,
                events_path=r2_conf.events_path,
                storage=youtube_storage,
            )
        )

    if failures:
        raise RuntimeError(
            f"Bootstrap compaction failed for: {', '.join(sorted(failures))}"
        )

    logger.info(
        "Bootstrap compaction finished successfully for provider=%s",
        args.provider,
    )


if __name__ == "__main__":
    main()
