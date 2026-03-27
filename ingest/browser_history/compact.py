"""Browser history compact CLI."""

import argparse
import logging

from ingest.browser_history.compaction import compact_browser_history_targets
from ingest.browser_history.storage import BrowserHistoryStorage
from ingest.compaction import resolve_target_months
from ingest.settings import IngestSettings

logger = logging.getLogger(__name__)


def _valid_month(value: str) -> int:
    month = int(value)
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError("month must be between 1 and 12")
    return month


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=_valid_month, default=None)
    args = parser.parse_args()
    if (args.year is None) != (args.month is None):
        raise SystemExit("Both --year and --month must be specified together")
    return args


def main() -> None:
    """Browser history compacted parquet を生成する。"""
    args = _parse_args()
    config = IngestSettings.load()
    if not config.duckdb or not config.duckdb.r2:
        raise ValueError("R2 configuration is required for compaction")

    r2_conf = config.duckdb.r2
    storage = BrowserHistoryStorage(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
        bucket_name=r2_conf.bucket_name,
        raw_path=r2_conf.raw_path,
        events_path=r2_conf.events_path,
        master_path=r2_conf.master_path,
    )

    targets = resolve_target_months(args.year, args.month)
    for year, month in targets:
        logger.info(
            "Compacting browser history dataset for year=%d month=%02d",
            year,
            month,
        )

    compact_browser_history_targets(storage, targets)


if __name__ == "__main__":
    main()
