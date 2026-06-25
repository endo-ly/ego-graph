"""Compacted parquet path resolution helpers."""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from dataset_catalog import DatasetDefinition

from backend.config import R2Config

COMPACTED_ROOT = "compacted/"


@dataclass(frozen=True)
class PartitionRef:
    """A month partition reference."""

    year: int
    month: int


def _normalize_path(path: str) -> str:
    return path.rstrip("/") + "/"


def _iter_months(utc_start: datetime, utc_end: datetime) -> list[PartitionRef]:
    """UTC datetime range から月パーティションのリストを生成する。"""
    refs: list[PartitionRef] = []
    current = date(utc_start.year, utc_start.month, 1)
    end_month = date(utc_end.year, utc_end.month, 1)

    while current <= end_month:
        refs.append(PartitionRef(year=current.year, month=current.month))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return refs


def _build_local_compacted_file(
    local_root: str,
    dataset: DatasetDefinition,
    partition: PartitionRef,
) -> Path:
    return (
        Path(local_root)
        / dataset.compacted_prefix(COMPACTED_ROOT)
        / f"year={partition.year}"
        / f"month={partition.month:02d}"
        / "data.parquet"
    )


def _build_r2_compacted_file(
    config: R2Config,
    dataset: DatasetDefinition,
    partition: PartitionRef,
) -> str:
    key = dataset.compacted_partition_key(
        COMPACTED_ROOT,
        year=partition.year,
        month=partition.month,
    )
    return f"s3://{config.bucket_name}/{key}"


def build_partition_paths(
    config: R2Config,
    dataset: DatasetDefinition,
    utc_start: datetime,
    utc_end: datetime,
) -> list[str]:
    """Build month-scoped parquet paths for compacted datasets."""
    paths: list[str] = []
    for partition in _iter_months(utc_start, utc_end):
        local_path = (
            _build_local_compacted_file(
                config.local_parquet_root,
                dataset,
                partition,
            )
            if config.local_parquet_root
            else None
        )
        if local_path and local_path.exists():
            paths.append(str(local_path))
            continue

        paths.append(_build_r2_compacted_file(config, dataset, partition))

    return paths


def build_dataset_glob(
    config: R2Config,
    dataset: DatasetDefinition,
) -> str:
    """Build all-data glob for compacted datasets."""
    if config.local_parquet_root:
        local_root = Path(config.local_parquet_root) / dataset.compacted_prefix(
            COMPACTED_ROOT
        )
        if any(local_root.rglob("*.parquet")):
            return str(local_root / "**" / "*.parquet")

    return (
        f"s3://{config.bucket_name}/"
        f"{dataset.compacted_prefix(COMPACTED_ROOT)}**/*.parquet"
    )
