"""Sync compacted parquet files from R2 to local mirror storage."""

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from pipelines.sources.common.compaction import COMPACTED_ROOT
from pipelines.sources.common.config import Config, R2Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalMirrorSyncResult:
    """Local mirror sync の実行サマリー。"""

    target_prefix: str
    downloaded_count: int
    skipped_count: int
    failed_count: int
    failed_keys_sample: tuple[str, ...]
    last_success_at: str | None

    def to_summary_dict(self) -> dict[str, object]:
        """SQLite result_summary_json に保存しやすい dict に変換する。"""
        return asdict(self)


def _resolve_r2_config(config: Config | None, r2_config: R2Config | None) -> R2Config:
    if r2_config is not None:
        return r2_config
    if config and config.duckdb and config.duckdb.r2:
        return config.duckdb.r2
    raise ValueError("R2 configuration is required")


def _should_skip_download(destination: Path, remote_size: int | None) -> bool:
    """既存ファイルサイズが一致する場合はダウンロードをスキップする。"""
    if not destination.exists() or remote_size is None:
        return False
    return destination.stat().st_size == remote_size


def run_local_mirror_sync(
    *,
    config: Config | None = None,
    r2_config: R2Config | None = None,
    local_root: str | Path | None = None,
    target_prefix: str = COMPACTED_ROOT,
    failed_keys_sample_limit: int = 20,
) -> LocalMirrorSyncResult:
    """compacted parquet を R2 から local mirror へ同期する。"""
    resolved_r2 = _resolve_r2_config(config, r2_config)
    root = Path(local_root or resolved_r2.local_parquet_root or "data/parquet")
    root.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client(
        "s3",
        endpoint_url=resolved_r2.endpoint_url,
        aws_access_key_id=resolved_r2.access_key_id,
        aws_secret_access_key=resolved_r2.secret_access_key.get_secret_value(),
        region_name="auto",
    )
    paginator = s3.get_paginator("list_objects_v2")

    downloaded_count = 0
    skipped_count = 0
    failed_keys: list[str] = []

    for page in paginator.paginate(
        Bucket=resolved_r2.bucket_name,
        Prefix=target_prefix,
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            destination = root / Path(key)
            tmp_destination = destination.with_suffix(destination.suffix + ".tmp")
            destination.parent.mkdir(parents=True, exist_ok=True)

            if _should_skip_download(destination, obj.get("Size")):
                skipped_count += 1
                continue

            try:
                s3.download_file(
                    resolved_r2.bucket_name,
                    key,
                    str(tmp_destination),
                )
                os.replace(tmp_destination, destination)
                downloaded_count += 1
            except ClientError:
                logger.exception("Failed to sync compacted parquet: %s", key)
                if tmp_destination.exists():
                    tmp_destination.unlink()
                failed_keys.append(key)

    last_success_at = None
    if not failed_keys:
        last_success_at = datetime.now(timezone.utc).isoformat()

    return LocalMirrorSyncResult(
        target_prefix=target_prefix,
        downloaded_count=downloaded_count,
        skipped_count=skipped_count,
        failed_count=len(failed_keys),
        failed_keys_sample=tuple(failed_keys[:failed_keys_sample_limit]),
        last_success_at=last_success_at,
    )
