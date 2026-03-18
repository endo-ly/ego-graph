"""Sync compacted parquet files from R2 to local storage."""

import argparse
import logging
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from backend.config import BackendConfig
from backend.infrastructure.database.parquet_paths import COMPACTED_ROOT

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None)
    return parser.parse_args()


def main() -> None:
    """Download compacted parquet files to the local mirror directory."""
    args = _parse_args()
    config = BackendConfig.from_env()
    if config.r2 is None:
        raise ValueError("R2 configuration is required")

    local_root = Path(args.root or config.r2.local_parquet_root or "data/parquet")
    local_root.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client(
        "s3",
        endpoint_url=config.r2.endpoint_url,
        aws_access_key_id=config.r2.access_key_id,
        aws_secret_access_key=config.r2.secret_access_key.get_secret_value(),
        region_name="auto",
    )
    paginator = s3.get_paginator("list_objects_v2")

    downloaded = 0
    for page in paginator.paginate(
        Bucket=config.r2.bucket_name,
        Prefix=COMPACTED_ROOT,
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            relative_path = Path(key)
            destination = local_root / relative_path
            tmp_destination = destination.with_suffix(destination.suffix + ".tmp")
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                s3.download_file(config.r2.bucket_name, key, str(tmp_destination))
                os.replace(tmp_destination, destination)
                downloaded += 1
            except ClientError:
                logger.exception("Failed to sync compacted parquet: %s", key)
                if tmp_destination.exists():
                    tmp_destination.unlink()
                continue

    logger.info("Downloaded %d compacted parquet files into %s", downloaded, local_root)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    main()
