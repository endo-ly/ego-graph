"""Google Health Raw JSONからの新スキーマ再構築。"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
from dataset_catalog import datasets

from pipelines.maintenance.progress import (
    ProgressReporter,
    StderrProgressReporter,
)
from pipelines.sources.common.compaction import normalize_dataframe_for_dataset
from pipelines.sources.google_health.data_types import DATA_TYPE_BY_NAME
from pipelines.sources.google_health.normalizer import (
    aggregate_daily_metrics,
    normalize_google_health_payload,
)
from pipelines.sources.google_health.raw_stream import (
    RawPointChunk,
    iter_raw_point_chunks,
)
from pipelines.sources.google_health.timezone import projection_row_local_date
from pipelines.sources.google_health.writer import GoogleHealthWriter

RAW_REPLAY_CHUNK_SIZE = 5_000

_RAW_KEY_PATTERN = re.compile(
    r"^connection_id=(?P<connection_id>[^/]+)/"
    r"data_type=(?P<data_type>[^/]+)/from=(?P<date_from>\d{4}-\d{2}-\d{2})/"
    r"to=(?P<date_to>\d{4}-\d{2}-\d{2})/run_id=(?P<run_id>[^/]+)\.json$"
)


@dataclass(frozen=True)
class RawReplayEntry:
    """再処理対象Raw JSONの保存情報。"""

    key: str
    connection_id: str
    data_type: str
    date_from: date
    date_to: date
    run_id: str
    last_modified: datetime | None = None


@dataclass(frozen=True)
class _PreparedReplayEntry:
    """1 Raw Entryの準備結果。"""

    validated_record_count: int
    replayed_record_count: int


def replay_google_health_raw(
    writer: GoogleHealthWriter,
    *,
    timezone: ZoneInfo | None = None,
    reset_compacted: bool = False,
    selected_dataset_ids: tuple[str, ...] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Raw JSONを新Normalizerで再処理し、eventsとcompactedを再生成する。

    ``reset_compacted`` は新世代へ全面切り替えするときだけ明示的に指定する。
    falseの場合は対象Rawの期間だけrange replaceするため、部分的な再構築にも
    利用できる。

    正規化結果は1 Raw Entryの処理中だけ保持する。日付範囲やDatasetを指定した
    部分再構築では、対象外のRawを読み飛ばし、対象外のprojectionを保存しない。
    """
    timezone = timezone or writer.timezone
    progress = progress or StderrProgressReporter()
    selected_dataset_ids = _validate_dataset_selection(selected_dataset_ids)
    if (date_from is None) != (date_to is None):
        raise ValueError("invalid_date_range: date_from and date_to are required")
    if date_from is not None and date_to is not None and date_from >= date_to:
        raise ValueError("invalid_date_range: date_from must be before date_to")

    entries = list_raw_entries(writer)
    entries = [
        entry
        for entry in entries
        if _entry_overlaps(entry, date_from=date_from, date_to=date_to)
    ]
    started_at = time.monotonic()

    validated_record_count = 0
    replayed_record_count = 0
    for index, entry in enumerate(entries, start=1):
        prepared = _prepare_replay_entry(
            writer,
            entry,
            timezone=timezone,
            selected_dataset_ids=selected_dataset_ids,
            date_from=date_from,
            date_to=date_to,
        )
        validated_record_count += prepared.validated_record_count
        replayed_record_count += prepared.replayed_record_count
        progress.report("validate", index, len(entries), entry.data_type)

    if reset_compacted:
        # 破損Rawが残っている場合でも、検証済みでない状態のcompactedを先に
        # 削除しない。全entryのnormalizeが成功した後で全面再構築を開始する。
        writer.reset_compacted(selected_dataset_ids=selected_dataset_ids)

    compacted_partition_keys = {
        dataset_id: set() for dataset_id in selected_dataset_ids
    }
    for index, entry in enumerate(entries, start=1):
        entry_dataset_ids = _selected_entry_dataset_ids(
            entry.data_type,
            selected_dataset_ids,
        )
        event_id = replay_event_id(entry)
        if entry_dataset_ids:
            compact_from = entry.date_from
            compact_to = entry.date_to
            if date_from is not None and date_to is not None:
                compact_from = max(compact_from, date_from)
                compact_to = min(compact_to, date_to)
            compacted_keys = writer.compact_range(
                connection_id=entry.connection_id,
                selected_data_types=(entry.data_type,),
                date_from=compact_from,
                date_to=compact_to,
                run_id=event_id,
                selected_dataset_ids=entry_dataset_ids,
            )
            for key in compacted_keys:
                for dataset in _google_health_datasets():
                    if dataset.dataset_id in entry_dataset_ids and key.startswith(
                        dataset.compacted_prefix(writer.compacted_path)
                    ):
                        compacted_partition_keys[dataset.dataset_id].add(key)
                        break
        progress.report("replay", index, len(entries), entry.data_type)

    return {
        "provider": "google_health",
        "operation": "raw_replay",
        "status": "succeeded",
        "raw_count": len(entries),
        "validated_count": len(entries),
        "validated_record_count": validated_record_count,
        "replayed_count": len(entries),
        "record_count": replayed_record_count,
        "compacted_partition_counts": {
            dataset_id: len(keys)
            for dataset_id, keys in compacted_partition_keys.items()
        },
        "duration_seconds": round(time.monotonic() - started_at, 3),
    }


def replay_event_id(entry: RawReplayEntry) -> str:
    """Raw keyから再現可能なevents run IDを生成する。"""
    digest = hashlib.sha256(entry.key.encode("utf-8")).hexdigest()
    return f"raw-replay-{digest}"


def list_raw_entries(writer: GoogleHealthWriter) -> list[RawReplayEntry]:
    """R2上のGoogle Health Raw JSONを保存順に列挙する。"""
    prefix = f"{writer.raw_path}google_health/"
    paginator = writer.s3.get_paginator("list_objects_v2")
    entries: list[RawReplayEntry] = []
    for page in paginator.paginate(Bucket=writer.bucket_name, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if not isinstance(key, str):
                continue
            relative_key = key.removeprefix(prefix)
            match = _RAW_KEY_PATTERN.match(relative_key)
            if match is None:
                continue
            values = match.groupdict()
            try:
                last_modified = item.get("LastModified")
                if isinstance(last_modified, datetime) and last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=UTC)
                if not isinstance(last_modified, datetime):
                    last_modified = None
                entries.append(
                    RawReplayEntry(
                        key=key,
                        connection_id=values["connection_id"],
                        data_type=values["data_type"],
                        date_from=date.fromisoformat(values["date_from"]),
                        date_to=date.fromisoformat(values["date_to"]),
                        run_id=values["run_id"],
                        last_modified=last_modified,
                    )
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"invalid_raw_google_health_key: {key}") from exc
    return sorted(entries, key=_entry_sort_key)


def _prepare_replay_entry(
    writer: GoogleHealthWriter,
    entry: RawReplayEntry,
    *,
    timezone: ZoneInfo,
    selected_dataset_ids: tuple[str, ...],
    date_from: date | None,
    date_to: date | None,
) -> _PreparedReplayEntry:
    """1 Rawを一度だけstreaming処理し、eventsを準備する。"""
    entry_dataset_ids = _selected_entry_dataset_ids(
        entry.data_type,
        selected_dataset_ids,
    )
    compact_from = entry.date_from
    compact_to = entry.date_to
    if date_from is not None and date_to is not None:
        compact_from = max(compact_from, date_from)
        compact_to = min(compact_to, date_to)

    validated_record_count = 0
    replayed_record_count = 0
    raw_point_count = 0
    daily_rows: list[dict[str, Any]] = []
    ingested_at = datetime.now(tz=UTC)

    with TemporaryDirectory(prefix="google-health-replay-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        staged_files: dict[str, dict[tuple[int, int], list[Path]]] = {}
        body = _open_raw_body(writer, entry.key)
        try:
            for chunk_index, chunk in enumerate(
                iter_raw_point_chunks(
                    body,
                    chunk_size=RAW_REPLAY_CHUNK_SIZE,
                ),
                start=1,
            ):
                raw_point_count += len(chunk.points)
                normalized = _normalize_chunk(
                    entry,
                    chunk,
                    timezone=timezone,
                    ingested_at=ingested_at,
                )
                validated_record_count += len(normalized["records"])
                daily_rows.extend(normalized["daily_metrics"])
                selected = _select_normalized_rows(
                    normalized,
                    selected_dataset_ids=entry_dataset_ids,
                    timezone=timezone,
                    date_from=date_from,
                    date_to=date_to,
                )
                selected["daily_metrics"] = []
                replayed_record_count += sum(len(rows) for rows in selected.values())
                _stage_rows(
                    staged_files,
                    temporary_root,
                    selected,
                    chunk_index=chunk_index,
                )
                del selected, normalized
        except ValueError as exc:
            if str(exc).startswith(
                (
                    "invalid_raw_google_health_json",
                    "invalid_raw_google_health_payload",
                )
            ):
                raise ValueError(f"{exc}: {entry.key}") from exc
            raise
        finally:
            _close_raw_body(body)

        if raw_point_count > 0 and validated_record_count == 0:
            raise ValueError(f"invalid_raw_google_health_record: {entry.key}")

        daily_metrics = aggregate_daily_metrics(daily_rows)
        selected_daily = _select_normalized_rows(
            {"daily_metrics": daily_metrics},
            selected_dataset_ids=entry_dataset_ids,
            timezone=timezone,
            date_from=date_from,
            date_to=date_to,
        )
        replayed_record_count += len(selected_daily["daily_metrics"])
        _stage_rows(
            staged_files,
            temporary_root,
            selected_daily,
            chunk_index="daily",
        )
        event_files = _merge_staged_files(staged_files, temporary_root)
        if entry_dataset_ids:
            writer.replace_events_from_parquet(
                run_id=replay_event_id(entry),
                event_files=event_files,
                selected_data_types=(entry.data_type,),
                date_from=compact_from,
                date_to=compact_to,
                selected_dataset_ids=entry_dataset_ids,
            )

    return _PreparedReplayEntry(
        validated_record_count=validated_record_count,
        replayed_record_count=replayed_record_count,
    )


def _open_raw_body(writer: GoogleHealthWriter, key: str) -> Any:
    """Raw JSONのstreaming bodyを取得する。"""
    response = writer.s3.get_object(Bucket=writer.bucket_name, Key=key)
    try:
        return response["Body"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid_raw_google_health_json: {key}") from exc


def _close_raw_body(body: Any) -> None:
    """Raw JSONのstreaming bodyを閉じる。"""
    close = getattr(body, "close", None)
    if callable(close):
        close()


def _normalize_chunk(
    entry: RawReplayEntry,
    chunk: RawPointChunk,
    *,
    timezone: ZoneInfo,
    ingested_at: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """1 chunkを既存Normalizerで正規化する。"""
    normalized = normalize_google_health_payload(
        connection_id=entry.connection_id,
        data_type=DATA_TYPE_BY_NAME[entry.data_type],
        payload=chunk.as_payload(),
        raw_ref=entry.key,
        ingested_at=ingested_at,
        timezone=timezone,
    )
    return normalized


def _stage_rows(
    staged_files: dict[str, dict[tuple[int, int], list[Path]]],
    temporary_root: Path,
    records: Mapping[str, list[dict[str, Any]]],
    *,
    chunk_index: int | str,
) -> None:
    """正規化chunkをDataset・月単位の一時Parquetへ書き出す。"""
    datasets_by_name = {
        dataset.dataset_id.split(".", 1)[1]: dataset
        for dataset in _google_health_datasets()
    }
    for dataset_name, rows in records.items():
        if not rows:
            continue
        dataset = datasets_by_name.get(dataset_name)
        if dataset is None or dataset.time_column is None:
            continue
        rows_by_month: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for row in rows:
            month = _row_month(row, dataset.time_column)
            rows_by_month.setdefault(month, []).append(row)
        for (year, month), month_rows in sorted(rows_by_month.items()):
            path = (
                temporary_root
                / "chunks"
                / dataset_name
                / f"year={year}"
                / f"month={month:02d}"
                / f"chunk-{chunk_index}.parquet"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            dataframe = normalize_dataframe_for_dataset(
                pd.DataFrame(month_rows),
                dataset,
            )
            dataframe.to_parquet(path, index=False, engine="pyarrow")
            staged_files.setdefault(dataset_name, {}).setdefault(
                (year, month), []
            ).append(path)


def _merge_staged_files(
    staged_files: Mapping[str, Mapping[tuple[int, int], list[Path]]],
    temporary_root: Path,
) -> dict[str, dict[tuple[int, int], Path]]:
    """chunk ParquetをDataset・月ごとにDuckDBで結合する。"""
    merged_files: dict[str, dict[tuple[int, int], Path]] = {}
    with duckdb.connect(":memory:") as connection:
        for dataset_name, partition_files in staged_files.items():
            for (year, month), paths in sorted(partition_files.items()):
                if len(paths) == 1:
                    merged_path = paths[0]
                else:
                    merged_path = (
                        temporary_root
                        / "events"
                        / dataset_name
                        / f"year={year}"
                        / f"month={month:02d}"
                        / "data.parquet"
                    )
                    merged_path.parent.mkdir(parents=True, exist_ok=True)
                    connection.read_parquet(
                        [str(path) for path in paths],
                        union_by_name=True,
                    ).write_parquet(str(merged_path))
                merged_files.setdefault(dataset_name, {})[(year, month)] = merged_path
    return merged_files


def _row_month(row: Mapping[str, Any], column: str) -> tuple[int, int]:
    """Projection rowのUTC/date partition月を返す。"""
    value = row.get(column)
    if isinstance(value, datetime):
        return value.year, value.month
    if isinstance(value, date):
        return value.year, value.month
    raise ValueError(f"invalid_projection_date: {column}")


def _validate_dataset_selection(
    selected_dataset_ids: tuple[str, ...] | None,
) -> tuple[str, ...]:
    """Google Health projectionの選択を検証する。"""
    all_ids = tuple(dataset.dataset_id for dataset in _google_health_datasets())
    if selected_dataset_ids is None:
        return all_ids
    normalized = tuple(dict.fromkeys(selected_dataset_ids))
    unknown = [dataset_id for dataset_id in normalized if dataset_id not in all_ids]
    if unknown:
        raise ValueError(
            f"invalid_dataset_id: unknown Google Health dataset: {', '.join(unknown)}"
        )
    if not normalized:
        raise ValueError("invalid_dataset_id: at least one dataset is required")
    return normalized


def _google_health_datasets():
    return (
        datasets.GOOGLE_HEALTH_RECORDS,
        datasets.GOOGLE_HEALTH_DAILY_METRICS,
        datasets.GOOGLE_HEALTH_SAMPLES,
        datasets.GOOGLE_HEALTH_INTERVALS,
        datasets.GOOGLE_HEALTH_SESSIONS,
    )


def _selected_entry_dataset_ids(
    data_type_name: str,
    selected_dataset_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Raw Entryが生成し得るselected Datasetだけを返す。"""
    data_type = DATA_TYPE_BY_NAME[data_type_name]
    possible_names = set(data_type.projection_dataset_names)
    return tuple(
        dataset_id
        for dataset_id in selected_dataset_ids
        if dataset_id.split(".", 1)[1] in possible_names
    )


def _select_normalized_rows(
    normalized: dict[str, list[dict[str, Any]]],
    *,
    selected_dataset_ids: tuple[str, ...],
    timezone: ZoneInfo,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, list[dict[str, Any]]]:
    """選択されたprojectionと日付範囲だけを返す。"""
    selected_names = {
        dataset_id.split(".", 1)[1] for dataset_id in selected_dataset_ids
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for dataset_name, rows in normalized.items():
        if dataset_name not in selected_names:
            result[dataset_name] = []
            continue
        if date_from is None or date_to is None:
            result[dataset_name] = rows
            continue
        result[dataset_name] = [
            row
            for row in rows
            if date_from
            <= projection_row_local_date(dataset_name, row, timezone)
            < date_to
        ]
    return result


def _entry_overlaps(
    entry: RawReplayEntry,
    *,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    """Raw Entryが指定日付範囲と重なるか返す。"""
    if date_from is None or date_to is None:
        return True
    return entry.date_from < date_to and entry.date_to > date_from


def _entry_sort_key(entry: RawReplayEntry) -> tuple[str, datetime, str]:
    """Rawの保存時刻を優先し、時刻がないテスト/互換実装はkeyで安定化する。"""
    return (
        entry.connection_id,
        entry.last_modified or datetime.min.replace(tzinfo=UTC),
        entry.key,
    )
