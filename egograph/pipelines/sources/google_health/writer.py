"""Google Health Raw JSON、events、compacted Parquetの保存。"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Any, BinaryIO
from zoneinfo import ZoneInfo

import boto3
import pandas as pd
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from dataset_catalog import DatasetDefinition, datasets
from dataset_catalog.validation import (
    validate_parquet_bytes,
    validate_parquet_file,
    validate_required_columns,
)

from pipelines.sources.common.compaction import (
    COMPACTED_ROOT,
    dataframe_to_parquet_bytes,
)
from pipelines.sources.google_health.timezone import (
    local_date_start_utc,
    projection_row_local_date,
)

logger = logging.getLogger(__name__)

MULTIPART_THRESHOLD_BYTES = 64 * 1024 * 1024
MULTIPART_CHUNK_SIZE_BYTES = 16 * 1024 * 1024

GOOGLE_HEALTH_DATASETS = (
    datasets.GOOGLE_HEALTH_RECORDS,
    datasets.GOOGLE_HEALTH_DAILY_METRICS,
    datasets.GOOGLE_HEALTH_SAMPLES,
    datasets.GOOGLE_HEALTH_INTERVALS,
    datasets.GOOGLE_HEALTH_SESSIONS,
)
GOOGLE_HEALTH_DATASETS_BY_ID = {
    dataset.dataset_id: dataset for dataset in GOOGLE_HEALTH_DATASETS
}


class GoogleHealthWriter:
    """Google HealthのR2保存と対象期間compactionを担う。"""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        raw_path: str = "raw/",
        events_path: str = "events/",
        compacted_path: str = COMPACTED_ROOT,
        timezone: ZoneInfo | None = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.raw_path = _normalize_path(raw_path)
        self.events_path = _normalize_path(events_path)
        self.compacted_path = _normalize_path(compacted_path)
        self.timezone = timezone or ZoneInfo("UTC")
        self._transfer_config = TransferConfig(
            multipart_threshold=MULTIPART_THRESHOLD_BYTES,
            multipart_chunksize=MULTIPART_CHUNK_SIZE_BYTES,
            use_threads=False,
        )
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def save_raw(
        self,
        *,
        connection_id: str,
        data_type: str,
        date_from: date,
        date_to: date,
        run_id: str,
        payload: dict[str, Any],
    ) -> str:
        """data type単位のAPIレスポンス原本を保存する。"""
        key = (
            f"{self.raw_path}google_health/"
            f"connection_id={connection_id}/data_type={data_type}/"
            f"from={date_from.isoformat()}/to={date_to.isoformat()}/"
            f"run_id={run_id}.json"
        )
        self._upload_bytes(
            key=key,
            data=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode(),
            content_type="application/json",
        )
        return key

    def save_events(
        self,
        *,
        run_id: str,
        records: dict[str, list[dict[str, Any]]],
        selected_dataset_ids: tuple[str, ...] | None = None,
    ) -> list[str]:
        """今回runの正規化行をevents Parquetへ保存する。"""
        attempted_keys: list[str] = []
        saved_keys: list[str] = []
        try:
            for dataset in _selected_datasets(selected_dataset_ids):
                dataset_name = _dataset_name(dataset)
                date_column = _date_column(dataset)
                rows_by_month: dict[tuple[int, int], list[dict[str, Any]]] = {}
                for row in records.get(dataset_name, []):
                    month = _row_month(row, date_column)
                    rows_by_month.setdefault(month, []).append(row)
                for (year, month), rows in sorted(rows_by_month.items()):
                    prefix = dataset.source_partition_prefix(
                        self.events_path,
                        year=year,
                        month=month,
                    )
                    key = f"{prefix}{run_id}.parquet"
                    data = _validated_parquet_bytes(dataset, rows)
                    attempted_keys.append(key)
                    self._upload_bytes(
                        key=key,
                        data=data,
                        content_type="application/octet-stream",
                    )
                    saved_keys.append(key)
        except Exception:
            for key in attempted_keys:
                try:
                    self._delete_if_exists(key)
                except Exception:
                    logger.exception(
                        "Google Health event cleanup failed: key=%s",
                        key,
                    )
            raise
        return saved_keys

    def replace_events(
        self,
        *,
        run_id: str,
        records: dict[str, list[dict[str, Any]]],
        selected_data_types: tuple[str, ...],
        date_from: date,
        date_to: date,
        selected_dataset_ids: tuple[str, ...] | None = None,
    ) -> list[str]:
        """deterministicなevent IDの正規化結果を置換する。

        Raw replayでは同じRaw keyから同じevent IDを生成するため、今回の
        正規化結果に行がないDatasetの既存eventも削除する。先に現行行の
        保存とschema検証を完了し、保存されなかった対象partitionだけを
        削除することで、空結果でも古いeventが再利用されないようにする。
        """
        saved_keys = self.save_events(
            run_id=run_id,
            records=records,
            selected_dataset_ids=selected_dataset_ids,
        )
        saved_key_set = set(saved_keys)
        for dataset in _selected_datasets(selected_dataset_ids):
            for year, month in _target_event_months(
                _dataset_name(dataset),
                selected_data_types=selected_data_types,
                date_from=date_from,
                date_to=date_to,
                timezone=self.timezone,
            ):
                event_key = self._event_key(dataset, year, month, run_id)
                if event_key not in saved_key_set:
                    self._delete_if_exists(event_key)
        return saved_keys

    def replace_events_from_parquet(
        self,
        *,
        run_id: str,
        event_files: Mapping[str, Mapping[tuple[int, int], Path]],
        selected_data_types: tuple[str, ...],
        date_from: date,
        date_to: date,
        selected_dataset_ids: tuple[str, ...] | None = None,
    ) -> list[str]:
        """一時Parquetからdeterministicなeventを置換する。

        Raw replayではnormalize結果をPython listへ戻さず、一時Parquetを
        Dataset・月単位でそのままeventsへアップロードする。今回の結果が
        空のpartitionは既存eventを削除し、古いprojectionが再利用されない
        ようにする。
        """
        saved_keys: list[str] = []
        saved_key_set: set[str] = set()
        for dataset in _selected_datasets(selected_dataset_ids):
            dataset_name = _dataset_name(dataset)
            for (year, month), path in sorted(
                event_files.get(dataset_name, {}).items()
            ):
                key = self._event_key(dataset, year, month, run_id)
                self._put_validated_parquet_file(dataset, path, key)
                saved_keys.append(key)
                saved_key_set.add(key)
            for year, month in _target_event_months(
                dataset_name,
                selected_data_types=selected_data_types,
                date_from=date_from,
                date_to=date_to,
                timezone=self.timezone,
            ):
                event_key = self._event_key(dataset, year, month, run_id)
                if event_key not in saved_key_set:
                    self._delete_if_exists(event_key)
        return saved_keys

    def compact_range(
        self,
        *,
        connection_id: str,
        selected_data_types: tuple[str, ...],
        date_from: date,
        date_to: date,
        run_id: str,
        selected_dataset_ids: tuple[str, ...] | None = None,
    ) -> list[str]:
        """既存compactedの対象範囲を今回runのeventsで置換する。"""
        compacted_keys: list[str] = []
        for dataset in _selected_datasets(selected_dataset_ids):
            dataset_name = _dataset_name(dataset)
            for year, month in _target_event_months(
                dataset_name,
                selected_data_types=selected_data_types,
                date_from=date_from,
                date_to=date_to,
                timezone=self.timezone,
            ):
                compacted_key = self._compacted_key(dataset, year, month)
                existing = self._load_parquet(compacted_key)
                retained = _retain_outside_target(
                    existing,
                    connection_id=connection_id,
                    selected_data_types=selected_data_types,
                    dataset_name=dataset_name,
                    date_from=date_from,
                    date_to=date_to,
                    timezone=self.timezone,
                )
                event_key = self._event_key(dataset, year, month, run_id)
                current = self._load_parquet(event_key)
                merged = [*retained, *current]
                if not merged:
                    self._delete_if_exists(compacted_key)
                    continue
                self._upload_bytes(
                    key=compacted_key,
                    data=_validated_parquet_bytes(dataset, merged),
                    content_type="application/octet-stream",
                )
                compacted_keys.append(compacted_key)
        return compacted_keys

    def reset_compacted(
        self,
        *,
        selected_dataset_ids: tuple[str, ...] | None = None,
    ) -> int:
        """Google Healthのcompacted Datasetを全削除する。

        Raw replayで新世代のcompactedを作り直す前にだけ使用する。eventsと
        Raw JSONは削除せず、Google Health Dataset以外にも触れない。
        """
        deleted = 0
        for dataset in _selected_datasets(selected_dataset_ids):
            prefix = dataset.compacted_prefix(self.compacted_path)
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = item.get("Key")
                    if isinstance(key, str):
                        self.s3.delete_object(Bucket=self.bucket_name, Key=key)
                        deleted += 1
        return deleted

    def _event_key(
        self,
        dataset: DatasetDefinition,
        year: int,
        month: int,
        run_id: str,
    ) -> str:
        prefix = dataset.source_partition_prefix(
            self.events_path,
            year=year,
            month=month,
        )
        return f"{prefix}{run_id}.parquet"

    def _compacted_key(self, dataset: DatasetDefinition, year: int, month: int) -> str:
        return dataset.compacted_partition_key(
            self.compacted_path,
            year=year,
            month=month,
        )

    def _load_parquet(self, key: str) -> list[dict[str, Any]]:
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                return []
            raise
        return pd.read_parquet(BytesIO(response["Body"].read())).to_dict(
            orient="records"
        )

    def _delete_if_exists(self, key: str) -> None:
        try:
            self.s3.delete_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
                raise

    def _put_validated_parquet_file(
        self,
        dataset: DatasetDefinition,
        path: Path,
        key: str,
    ) -> None:
        """ローカルParquetをschema検証後にstreaming uploadする。"""
        validate_parquet_file(dataset, path)
        size_bytes = path.stat().st_size
        with path.open("rb") as body:
            self._upload(
                key=key,
                body=body,
                size_bytes=size_bytes,
                content_type="application/octet-stream",
            )

    def _upload(
        self,
        *,
        key: str,
        body: BinaryIO,
        size_bytes: int,
        content_type: str,
    ) -> None:
        """R2へオブジェクトをmanaged uploadする。"""
        multipart = size_bytes >= MULTIPART_THRESHOLD_BYTES
        logger.info(
            "R2 upload started: key=%s size_bytes=%d multipart=%s",
            key,
            size_bytes,
            multipart,
        )
        started_at = monotonic()
        try:
            self.s3.upload_fileobj(
                body,
                self.bucket_name,
                key,
                ExtraArgs={"ContentType": content_type},
                Config=self._transfer_config,
            )
        except Exception as exc:
            logger.error(
                "R2 upload failed: key=%s size_bytes=%d multipart=%s error_type=%s",
                key,
                size_bytes,
                multipart,
                type(exc).__name__,
            )
            raise
        logger.info(
            "R2 upload completed: key=%s size_bytes=%d multipart=%s "
            "duration_seconds=%.3f",
            key,
            size_bytes,
            multipart,
            monotonic() - started_at,
        )

    def _upload_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        """bytesをR2へmanaged uploadする。"""
        with BytesIO(data) as body:
            self._upload(
                key=key,
                body=body,
                size_bytes=len(data),
                content_type=content_type,
            )


def _retain_outside_target(
    rows: list[dict[str, Any]],
    *,
    connection_id: str,
    selected_data_types: tuple[str, ...],
    dataset_name: str,
    date_from: date,
    date_to: date,
    timezone: ZoneInfo,
) -> list[dict[str, Any]]:
    retained = []
    selected = set(selected_data_types)
    for row in rows:
        row_date = projection_row_local_date(dataset_name, row, timezone)
        is_target = (
            row.get("connection_id") == connection_id
            and row.get("data_type") in selected
            and date_from <= row_date < date_to
        )
        if not is_target:
            retained.append(row)
    return retained


def _dataset_name(dataset: DatasetDefinition) -> str:
    return dataset.dataset_id.split(".", 1)[1]


def _date_column(dataset: DatasetDefinition) -> str:
    if dataset.time_column is None:
        raise ValueError(f"time_column_required: {dataset.dataset_id}")
    return dataset.time_column


def _row_month(row: dict[str, Any], date_column: str) -> tuple[int, int]:
    value = _as_date(row[date_column])
    return value.year, value.month


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _target_months(
    dataset: str,
    *,
    date_from: date,
    date_to: date,
    timezone: ZoneInfo,
):
    if dataset in {"daily_metrics", "records"}:
        current = date(date_from.year, date_from.month, 1)
        limit = date_to
    else:
        start_utc = local_date_start_utc(date_from, timezone)
        end_utc = local_date_start_utc(date_to, timezone)
        current = date(start_utc.year, start_utc.month, 1)
        limit = end_utc.date() + timedelta(days=1)
    while current < limit:
        yield current.year, current.month
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )


def _target_event_months(
    dataset_name: str,
    *,
    selected_data_types: tuple[str, ...],
    date_from: date,
    date_to: date,
    timezone: ZoneInfo,
) -> tuple[tuple[int, int], ...]:
    """event保存・compactionで共有する対象partition月を返す。"""
    months = set(
        _target_months(
            dataset_name,
            date_from=date_from,
            date_to=date_to,
            timezone=timezone,
        )
    )
    if dataset_name == "sessions" and "sleep" in selected_data_types:
        sleep_start = local_date_start_utc(date_from - timedelta(days=1), timezone)
        months.add((sleep_start.year, sleep_start.month))
    return tuple(sorted(months))


def _normalize_path(path: str) -> str:
    return path.rstrip("/") + "/"


def _selected_datasets(
    selected_dataset_ids: tuple[str, ...] | None,
) -> tuple[DatasetDefinition, ...]:
    """指定されたGoogle Health projectionをCatalog順に返す。"""
    if selected_dataset_ids is None:
        return GOOGLE_HEALTH_DATASETS
    normalized = tuple(dict.fromkeys(selected_dataset_ids))
    unknown = [
        dataset_id
        for dataset_id in normalized
        if dataset_id not in GOOGLE_HEALTH_DATASETS_BY_ID
    ]
    if unknown:
        raise ValueError(
            f"invalid_dataset_id: unknown Google Health dataset: {', '.join(unknown)}"
        )
    if not normalized:
        raise ValueError("invalid_dataset_id: at least one dataset is required")
    selected = set(normalized)
    return tuple(
        dataset for dataset in GOOGLE_HEALTH_DATASETS if dataset.dataset_id in selected
    )


def _validated_parquet_bytes(
    dataset: DatasetDefinition,
    rows: list[dict[str, Any]],
) -> bytes:
    """契約検証を通過した rows を parquet bytes に変換する。"""
    df = pd.DataFrame(rows)
    validate_required_columns(dataset, df.columns)
    body = dataframe_to_parquet_bytes(df)
    validate_parquet_bytes(dataset, body)
    return body


def _parquet_bytes(rows: list[dict[str, Any]]) -> bytes:
    return dataframe_to_parquet_bytes(pd.DataFrame(rows))
