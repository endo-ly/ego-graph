"""Compacted parquet path resolution helpers."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.config import R2Config

COMPACTED_ROOT = "compacted/"


@dataclass(frozen=True)
class PartitionRef:
    """A month partition reference."""

    year: int
    month: int


def _normalize_path(path: str) -> str:
    return path.rstrip("/") + "/"


def _iter_months(start_date: date, end_date: date) -> list[PartitionRef]:
    refs: list[PartitionRef] = []
    current = start_date.replace(day=1)
    end_month = end_date.replace(day=1)

    while current <= end_month:
        refs.append(PartitionRef(year=current.year, month=current.month))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return refs


def _build_local_compacted_file(
    local_root: str,
    data_domain: str,
    dataset_path: str,
    partition: PartitionRef,
) -> Path:
    return (
        Path(local_root)
        / "compacted"
        / data_domain
        / dataset_path
        / f"year={partition.year}"
        / f"month={partition.month:02d}"
        / "data.parquet"
    )


def _build_r2_compacted_file(
    config: R2Config,
    data_domain: str,
    dataset_path: str,
    partition: PartitionRef,
) -> str:
    return (
        f"s3://{config.bucket_name}/{COMPACTED_ROOT}{data_domain}/{dataset_path}/"
        f"year={partition.year}/month={partition.month:02d}/data.parquet"
    )


def build_partition_paths(
    config: R2Config,
    data_domain: str,
    dataset_path: str,
    start_date: date,
    end_date: date,
) -> list[str]:
    """Build month-scoped parquet paths for compacted datasets."""
    paths: list[str] = []
    for partition in _iter_months(start_date, end_date):
        local_path = (
            _build_local_compacted_file(
                config.local_parquet_root, data_domain, dataset_path, partition
            )
            if config.local_parquet_root
            else None
        )
        if local_path and local_path.exists():
            paths.append(str(local_path))
            continue

        paths.append(
            _build_r2_compacted_file(config, data_domain, dataset_path, partition)
        )

    return paths


def build_dataset_glob(
    config: R2Config,
    data_domain: str,
    dataset_path: str,
) -> str:
    """Build all-data glob for compacted datasets."""
    if config.local_parquet_root:
        local_root = (
            Path(config.local_parquet_root) / "compacted" / data_domain / dataset_path
        )
        if any(local_root.rglob("*.parquet")):
            return str(local_root / "**" / "*.parquet")

    return (
        f"s3://{config.bucket_name}/{COMPACTED_ROOT}{data_domain}/"
        f"{dataset_path}/**/*.parquet"
    )
