"""Compaction helpers for pipelines source modules."""

import logging
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

COMPACTED_ROOT = "compacted/"
_YEAR_MONTH_PATTERN = re.compile(r"year=(\d{4})/month=(\d{2})/")


def _normalize_path(path: str) -> str:
    return path.rstrip("/") + "/"


def build_compacted_key(
    compacted_path: str,
    data_domain: str,
    dataset_path: str,
    year: int,
    month: int,
) -> str:
    """月次 compacted parquet の key を組み立てる。"""
    compacted_path = _normalize_path(compacted_path)
    return (
        f"{compacted_path}{data_domain}/{dataset_path}/"
        f"year={year}/month={month:02d}/data.parquet"
    )


def compact_records(
    records: list[dict[str, Any]],
    dedupe_key: str,
    sort_by: str | None = None,
) -> pd.DataFrame:
    """レコードを重複排除して compact する。"""
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    if dedupe_key not in df.columns:
        raise ValueError(f"Missing dedupe key column: {dedupe_key}")

    if sort_by:
        if sort_by in df.columns:
            df = df.sort_values(sort_by)
        else:
            logger.warning(
                "sort_by column '%s' not found during compaction. columns=%s",
                sort_by,
                list(df.columns),
            )

    return df.drop_duplicates(subset=[dedupe_key], keep="last").reset_index(drop=True)


def dataframe_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame を parquet bytes へ変換する。"""
    buffer = BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    buffer.seek(0)
    return buffer.getvalue()


def resolve_target_months(
    year: int | None = None,
    month: int | None = None,
    *,
    now: datetime | None = None,
) -> list[tuple[int, int]]:
    """compact 対象月を決定する。"""
    if year is not None and month is not None:
        return [(year, month)]

    current = now or datetime.now(timezone.utc)
    current_pair = (current.year, current.month)
    if current.month == 1:
        previous_pair = (current.year - 1, 12)
    else:
        previous_pair = (current.year, current.month - 1)
    return [previous_pair, current_pair]


def read_parquet_records_from_prefix(
    s3_client: Any,
    bucket_name: str,
    prefix: str,
) -> list[dict[str, Any]]:
    """prefix 配下の parquet object をすべて読み込む。"""
    paginator = s3_client.get_paginator("list_objects_v2")
    frames: list[pd.DataFrame] = []

    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".parquet"):
                continue
            response = s3_client.get_object(Bucket=bucket_name, Key=obj["Key"])
            frames.append(pd.read_parquet(BytesIO(response["Body"].read())))

    if not frames:
        return []

    combined = pd.concat(frames, ignore_index=True)
    return combined.to_dict(orient="records")


def discover_available_months(
    s3_client: Any,
    bucket_name: str,
    source_prefix: str,
) -> list[tuple[int, int]]:
    """prefix 配下の year/month partition を列挙する。"""
    paginator = s3_client.get_paginator("list_objects_v2")
    months: set[tuple[int, int]] = set()

    for page in paginator.paginate(Bucket=bucket_name, Prefix=source_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".parquet"):
                continue
            match = _YEAR_MONTH_PATTERN.search(key)
            if match is None:
                logger.debug(
                    "Skipping parquet key without year/month partition: %s",
                    key,
                )
                continue
            months.add((int(match.group(1)), int(match.group(2))))

    return sorted(months)
