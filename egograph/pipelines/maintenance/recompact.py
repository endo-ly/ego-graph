"""Dataset Catalogを基準にしたcompact済みParquetの再構築。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from botocore.exceptions import ClientError
from dataset_catalog import (
    ALL_DATASETS,
    CompactionStrategy,
    DatasetDefinition,
    PartitionPolicy,
    get_dataset,
)

from pipelines.maintenance.progress import ProgressReporter, StderrProgressReporter
from pipelines.sources.common.compaction import (
    COMPACTED_ROOT,
    compact_records,
    discover_available_months,
    normalize_dataframe_for_dataset,
    read_parquet_records_from_prefix,
    write_compacted_parquet,
)
from pipelines.sources.google_health.replay import replay_google_health_raw
from pipelines.sources.google_health.writer import GoogleHealthWriter

logger = logging.getLogger(__name__)

_COMPACTED_MONTH_PATTERN = re.compile(
    r"^year=(?P<year>\d{4})/month=(?P<month>\d{2})/data\.parquet$"
)


@dataclass(frozen=True)
class RecompactRequest:
    """Global recompactの入力条件。"""

    provider: str | None = None
    dataset_id: str | None = None
    year: int | None = None
    month: int | None = None
    prune: bool = False

    def __post_init__(self) -> None:
        if self.provider is not None and self.dataset_id is not None:
            raise ValueError("invalid_filters: provider and dataset cannot be combined")
        if self.provider is not None and not self.provider.strip():
            raise ValueError("invalid_provider: provider is required")
        if self.dataset_id is not None and not self.dataset_id.strip():
            raise ValueError("invalid_dataset_id: dataset is required")
        if (self.year is None) != (self.month is None):
            raise ValueError("invalid_date_range: year and month are required together")
        if self.year is not None:
            if isinstance(self.year, bool) or not 1 <= self.year <= 9999:
                raise ValueError("invalid_year: year must be 1..9999")
        if self.month is not None:
            if isinstance(self.month, bool) or not 1 <= self.month <= 12:
                raise ValueError("invalid_month: month must be 1..12")


@dataclass(frozen=True)
class RecompactTargetResult:
    """Dataset単位のrecompact結果。"""

    dataset_id: str
    strategy: str
    status: str
    partition_count: int
    reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """CLI JSONへ変換する。"""
        result: dict[str, Any] = {
            "dataset": self.dataset_id,
            "strategy": self.strategy,
            "status": self.status,
            "partitions": self.partition_count,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        if self.error is not None:
            result["error"] = self.error
        return result


@dataclass(frozen=True)
class RecompactResult:
    """Global recompactの集計結果。"""

    status: str
    succeeded: int
    skipped: int
    failed: int
    targets: tuple[RecompactTargetResult, ...]

    def to_dict(self) -> dict[str, Any]:
        """CLI JSONへ変換する。"""
        return {
            "operation": "recompact",
            "status": self.status,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "targets": [target.to_dict() for target in self.targets],
        }


class _SourceSnapshotMissing(Exception):
    """snapshot sourceが存在しない場合にrecompactをskipする。"""


class RecompactService:
    """Catalogのcompaction strategyをdispatchする保守サービス。"""

    def __init__(
        self,
        *,
        s3_client: Any,
        bucket_name: str,
        events_path: str = "events/",
        master_path: str = "master/",
        compacted_path: str = COMPACTED_ROOT,
        timezone: ZoneInfo | None = None,
        google_health_writer: GoogleHealthWriter | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.s3 = s3_client
        self.bucket_name = bucket_name
        self.events_path = _normalize_path(events_path)
        self.master_path = _normalize_path(master_path)
        self.compacted_path = _normalize_path(compacted_path)
        self.timezone = timezone or ZoneInfo("UTC")
        self.google_health_writer = google_health_writer
        self.progress = progress or StderrProgressReporter()

    def run(self, request: RecompactRequest) -> RecompactResult:
        """指定条件のDatasetを再compactする。"""
        selected = _select_datasets(request)
        result_by_id: dict[str, RecompactTargetResult] = {}

        range_replace = tuple(
            dataset
            for dataset in selected
            if dataset.compaction_strategy is CompactionStrategy.RANGE_REPLACE
        )
        if range_replace:
            self._run_range_replace(request, range_replace, result_by_id)

        for dataset in selected:
            if dataset.dataset_id in result_by_id:
                continue
            if dataset.compaction_strategy is CompactionStrategy.NONE:
                result_by_id[dataset.dataset_id] = RecompactTargetResult(
                    dataset_id=dataset.dataset_id,
                    strategy=dataset.compaction_strategy.value,
                    status="skipped",
                    partition_count=0,
                    reason="compaction_strategy_none",
                )
                continue
            try:
                if dataset.compaction_strategy is CompactionStrategy.APPEND_DEDUPE:
                    partition_count = self._recompact_monthly(dataset, request)
                elif dataset.compaction_strategy is CompactionStrategy.SNAPSHOT_UPSERT:
                    partition_count = self._recompact_snapshot(dataset)
                else:
                    raise ValueError(
                        "unsupported_compaction_strategy: "
                        f"{dataset.compaction_strategy.value}"
                    )
            except _SourceSnapshotMissing:
                result_by_id[dataset.dataset_id] = RecompactTargetResult(
                    dataset_id=dataset.dataset_id,
                    strategy=dataset.compaction_strategy.value,
                    status="skipped",
                    partition_count=0,
                    reason="source_not_found",
                )
            except Exception as exc:
                logger.exception(
                    "Recompact failed: dataset=%s error=%s",
                    dataset.dataset_id,
                    exc,
                )
                result_by_id[dataset.dataset_id] = RecompactTargetResult(
                    dataset_id=dataset.dataset_id,
                    strategy=dataset.compaction_strategy.value,
                    status="failed",
                    partition_count=0,
                    error=str(exc),
                )
            else:
                result_by_id[dataset.dataset_id] = RecompactTargetResult(
                    dataset_id=dataset.dataset_id,
                    strategy=dataset.compaction_strategy.value,
                    status="succeeded",
                    partition_count=partition_count,
                )

        targets = tuple(result_by_id[dataset.dataset_id] for dataset in selected)
        succeeded = sum(target.status == "succeeded" for target in targets)
        skipped = sum(target.status == "skipped" for target in targets)
        failed = sum(target.status == "failed" for target in targets)
        if failed == 0:
            status = "succeeded"
        elif succeeded or skipped:
            status = "partial_failed"
        else:
            status = "failed"
        return RecompactResult(
            status=status,
            succeeded=succeeded,
            skipped=skipped,
            failed=failed,
            targets=targets,
        )

    def _run_range_replace(
        self,
        request: RecompactRequest,
        datasets: tuple[DatasetDefinition, ...],
        result_by_id: dict[str, RecompactTargetResult],
    ) -> None:
        """RANGE_REPLACE Datasetをprovider adapterへ委譲する。"""
        providers = {dataset.provider for dataset in datasets}
        if providers != {"google_health"}:
            error = "unsupported_range_replace_provider: provider adapter is missing"
            for dataset in datasets:
                result_by_id[dataset.dataset_id] = RecompactTargetResult(
                    dataset_id=dataset.dataset_id,
                    strategy=dataset.compaction_strategy.value,
                    status="failed",
                    partition_count=0,
                    error=error,
                )
            return
        try:
            if self.google_health_writer is None:
                raise ValueError("invalid_r2_config: Google Health writer is required")
            date_from, date_to = _request_month_range(request)
            replay_result = replay_google_health_raw(
                self.google_health_writer,
                reset_compacted=date_from is None,
                selected_dataset_ids=tuple(
                    dataset.dataset_id for dataset in datasets
                ),
                date_from=date_from,
                date_to=date_to,
                progress=self.progress,
            )
            partition_count = int(replay_result.get("replayed_count", 0))
        except Exception as exc:
            logger.exception("Google Health recompact failed: error=%s", exc)
            for dataset in datasets:
                result_by_id[dataset.dataset_id] = RecompactTargetResult(
                    dataset_id=dataset.dataset_id,
                    strategy=dataset.compaction_strategy.value,
                    status="failed",
                    partition_count=0,
                    error=str(exc),
                )
            return
        for dataset in datasets:
            result_by_id[dataset.dataset_id] = RecompactTargetResult(
                dataset_id=dataset.dataset_id,
                strategy=dataset.compaction_strategy.value,
                status="succeeded",
                partition_count=partition_count,
            )

    def _recompact_monthly(
        self,
        dataset: DatasetDefinition,
        request: RecompactRequest,
    ) -> int:
        """月次sourceを1 partitionずつcompactする。"""
        if dataset.partition_policy is not PartitionPolicy.MONTHLY:
            raise ValueError(
                "invalid_dataset: monthly compaction requires monthly partition: "
                f"{dataset.dataset_id}"
            )
        source_root = dataset.source_root(self.events_path, self.master_path)
        available_months = set(
            discover_available_months(
                self.s3,
                self.bucket_name,
                dataset.source_prefix(source_root),
            )
        )
        requested_months = _requested_months(request)
        target_months = (
            requested_months
            if requested_months is not None
            else sorted(available_months)
        )
        compacted_months = set(self._discover_compacted_months(dataset))
        prune_scope = (
            set(requested_months)
            if requested_months is not None
            else available_months | compacted_months
        )
        rebuilt_months: set[tuple[int, int]] = set()
        processed = 0
        for index, (year, month) in enumerate(target_months, start=1):
            self.progress.report(
                "compact",
                index,
                len(target_months),
                f"{dataset.dataset_id} {year}-{month:02d}",
            )
            if (year, month) not in available_months:
                continue
            processed += 1
            source_prefix = dataset.source_partition_prefix(
                source_root,
                year=year,
                month=month,
            )
            records = read_parquet_records_from_prefix(
                self.s3,
                self.bucket_name,
                source_prefix,
                dataset=dataset,
            )
            if not records:
                continue
            compacted = compact_records(
                records,
                dedupe_key=dataset.required_dedupe_key(),
                sort_by=dataset.sort_key,
                dataset=dataset,
            )
            write_compacted_parquet(
                self.s3,
                self.bucket_name,
                dataset.compacted_partition_key(
                    self.compacted_path,
                    year=year,
                    month=month,
                ),
                compacted,
                dataset,
            )
            rebuilt_months.add((year, month))

        if request.prune:
            for year, month in sorted(compacted_months - rebuilt_months):
                if (year, month) not in prune_scope:
                    continue
                self.s3.delete_object(
                    Bucket=self.bucket_name,
                    Key=dataset.compacted_partition_key(
                        self.compacted_path,
                        year=year,
                        month=month,
                    ),
                )
        return processed

    def _recompact_snapshot(self, dataset: DatasetDefinition) -> int:
        """snapshot sourceを検証して固定compact keyへ保存する。"""
        if dataset.partition_policy is not PartitionPolicy.SNAPSHOT:
            raise ValueError(
                "invalid_dataset: snapshot compaction requires snapshot partition: "
                f"{dataset.dataset_id}"
            )
        source_key = dataset.source_snapshot_key(
            dataset.source_root(self.events_path, self.master_path)
        )
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=source_key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise _SourceSnapshotMissing from exc
            raise
        dataframe = pd.read_parquet(
            BytesIO(response["Body"].read()),
            engine="pyarrow",
        )
        dataframe = normalize_dataframe_for_dataset(dataframe, dataset)
        write_compacted_parquet(
            self.s3,
            self.bucket_name,
            dataset.compacted_snapshot_key(self.compacted_path),
            dataframe,
            dataset,
        )
        return 1

    def _discover_compacted_months(
        self,
        dataset: DatasetDefinition,
    ) -> list[tuple[int, int]]:
        """Datasetのcompact済み月を列挙する。"""
        prefix = dataset.compacted_prefix(self.compacted_path)
        paginator = self.s3.get_paginator("list_objects_v2")
        months: set[tuple[int, int]] = set()
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item.get("Key")
                if not isinstance(key, str):
                    continue
                match = _COMPACTED_MONTH_PATTERN.match(key.removeprefix(prefix))
                if match is not None:
                    months.add((int(match["year"]), int(match["month"])))
        return sorted(months)


def _select_datasets(request: RecompactRequest) -> tuple[DatasetDefinition, ...]:
    """requestに対応するDatasetをCatalog順に選ぶ。"""
    if request.dataset_id is not None:
        try:
            return (get_dataset(request.dataset_id),)
        except KeyError as exc:
            raise ValueError(
                "invalid_dataset_id: unknown dataset: "
                f"{request.dataset_id}"
            ) from exc
    if request.provider is not None:
        selected = tuple(
            dataset for dataset in ALL_DATASETS if dataset.provider == request.provider
        )
        if not selected:
            raise ValueError(
                "invalid_provider: unsupported provider: "
                f"{request.provider}"
            )
        return selected
    return ALL_DATASETS


def _requested_months(
    request: RecompactRequest,
) -> tuple[tuple[int, int], ...] | None:
    """requestの月指定をtupleへ変換する。"""
    if request.year is None or request.month is None:
        return None
    return ((request.year, request.month),)


def _request_month_range(
    request: RecompactRequest,
) -> tuple[date | None, date | None]:
    """Google Health用の指定月の半開区間を返す。"""
    if request.year is None or request.month is None:
        return None, None
    start = date(request.year, request.month, 1)
    end = (
        date(request.year + 1, 1, 1)
        if request.month == 12
        else date(request.year, request.month + 1, 1)
    )
    return start, end


def _normalize_path(path: str) -> str:
    """prefixを正規化する。"""
    return path.rstrip("/") + "/"


def _is_not_found(exc: ClientError) -> bool:
    """S3のオブジェクト不存在エラーか判定する。"""
    code = exc.response.get("Error", {}).get("Code")
    status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"NoSuchKey", "404"} or status_code == 404
