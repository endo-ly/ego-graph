"""Google Health Raw JSONからの新スキーマ再構築。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pipelines.sources.google_health.data_types import DATA_TYPE_BY_NAME
from pipelines.sources.google_health.normalizer import (
    aggregate_daily_metrics,
    normalize_google_health_payload,
)
from pipelines.sources.google_health.writer import GoogleHealthWriter

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


def replay_google_health_raw(
    writer: GoogleHealthWriter,
    *,
    timezone: ZoneInfo | None = None,
    reset_compacted: bool = False,
) -> dict[str, Any]:
    """Raw JSONを新Normalizerで再処理し、eventsとcompactedを再生成する。

    ``reset_compacted`` は新世代へ全面切り替えするときだけ明示的に指定する。
    falseの場合は対象Rawの期間だけrange replaceするため、部分的な再構築にも
    利用できる。
    """
    timezone = timezone or writer.timezone
    entries = list_raw_entries(writer)

    results: list[dict[str, Any]] = []
    normalized_entries: list[
        tuple[RawReplayEntry, dict[str, list[dict[str, Any]]]]
    ] = []
    for entry in entries:
        raw_payload = _load_raw(writer, entry.key)
        normalized = normalize_google_health_payload(
            connection_id=entry.connection_id,
            data_type=DATA_TYPE_BY_NAME[entry.data_type],
            payload=raw_payload,
            raw_ref=entry.key,
            timezone=timezone,
        )
        if _raw_point_count(raw_payload) > 0 and not normalized["records"]:
            raise ValueError(f"invalid_raw_google_health_record: {entry.key}")
        normalized_entries.append((entry, normalized))
        results.append(
            {
                "key": entry.key,
                "connection_id": entry.connection_id,
                "data_type": entry.data_type,
                "run_id": entry.run_id,
                "record_count": len(normalized["records"]),
            }
        )

    if reset_compacted:
        # 破損Rawが残っている場合でも、検証済みでない状態のcompactedを先に
        # 削除しない。全entryのnormalizeが成功した後で全面再構築を開始する。
        writer.reset_compacted()

    # 同じworkflow runのRawは1つのeventsファイルへまとめ、同じrunの全data
    # typeを1回でcompactする。データ型ごとにsave_events/compactすると、同じ
    # run_id・同じdataset/monthのParquetを上書きしたり、別data typeのcurrent
    # 行を重複追加したりするためである。各runをLastModified順にcompactし、
    # 遅延同期の後続runが先行runの対象範囲を置換する通常workflowを再現する。
    for batch in _run_batches(normalized_entries):
        batch_records = _merge_normalized(normalized for _entry, normalized in batch)
        run_id = batch[0][0].run_id
        writer.save_events(run_id=run_id, records=batch_records)
        writer.compact_range(
            connection_id=batch[0][0].connection_id,
            selected_data_types=tuple(sorted({entry.data_type for entry, _ in batch})),
            date_from=min(entry.date_from for entry, _ in batch),
            date_to=max(entry.date_to for entry, _ in batch),
            run_id=run_id,
        )
    return {
        "provider": "google_health",
        "operation": "raw_replay",
        "status": "succeeded",
        "raw_count": len(results),
        "results": results,
    }


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


def _load_raw(writer: GoogleHealthWriter, key: str) -> dict[str, Any]:
    response = writer.s3.get_object(Bucket=writer.bucket_name, Key=key)
    try:
        value = json.loads(response["Body"].read())
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_raw_google_health_json: {key}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid_raw_google_health_payload: {key}")
    return value


def _raw_point_count(payload: dict[str, Any]) -> int:
    count = 0
    for response in payload.get("reconcileResponses") or []:
        if isinstance(response, dict) and isinstance(response.get("dataPoints"), list):
            count += len(response["dataPoints"])
    for field in ("rollupResponses", "dailyRollupResponses"):
        for response in payload.get(field) or []:
            if isinstance(response, dict) and isinstance(
                response.get("rollupDataPoints"), list
            ):
                count += len(response["rollupDataPoints"])
    return count


def _run_batches(
    normalized_entries: list[tuple[RawReplayEntry, dict[str, list[dict[str, Any]]]]],
) -> list[list[tuple[RawReplayEntry, dict[str, list[dict[str, Any]]]]]]:
    """Rawを元workflow run単位へまとめ、取得保存時刻順に返す。"""
    grouped: dict[
        tuple[str, str], list[tuple[RawReplayEntry, dict[str, list[dict[str, Any]]]]]
    ] = {}
    for entry, normalized in normalized_entries:
        grouped.setdefault((entry.connection_id, entry.run_id), []).append(
            (entry, normalized)
        )
    batches = [
        sorted(batch, key=lambda item: _entry_sort_key(item[0]))
        for batch in grouped.values()
    ]
    return sorted(
        batches,
        key=lambda batch: min(_entry_sort_key(entry) for entry, _normalized in batch),
    )


def _merge_normalized(
    normalized_values: Any,
) -> dict[str, list[dict[str, Any]]]:
    """同一workflow runの正規化結果をevents保存用にまとめる。"""
    result: dict[str, list[dict[str, Any]]] = {
        "records": [],
        "daily_metrics": [],
        "samples": [],
        "intervals": [],
        "sessions": [],
    }
    for normalized in normalized_values:
        for dataset, rows in normalized.items():
            result[dataset].extend(rows)
    result["daily_metrics"] = aggregate_daily_metrics(result["daily_metrics"])
    return result


def _entry_sort_key(entry: RawReplayEntry) -> tuple[str, datetime, str]:
    """Rawの保存時刻を優先し、時刻がないテスト/互換実装はkeyで安定化する。"""
    return (
        entry.connection_id,
        entry.last_modified or datetime.min.replace(tzinfo=UTC),
        entry.key,
    )
