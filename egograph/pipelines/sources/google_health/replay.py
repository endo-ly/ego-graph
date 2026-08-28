"""Google Health Raw JSONからの新スキーマ再構築。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
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
    if reset_compacted:
        writer.reset_compacted()

    results: list[dict[str, Any]] = []
    normalized_by_connection: dict[str, list[dict[str, Any]]] = {}
    entries_by_connection: dict[str, list[RawReplayEntry]] = {}
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
        if reset_compacted:
            _append_normalized(
                normalized_by_connection.setdefault(entry.connection_id, []),
                normalized,
            )
            entries_by_connection.setdefault(entry.connection_id, []).append(entry)
        else:
            writer.save_events(run_id=entry.run_id, records=normalized)
            writer.compact_range(
                connection_id=entry.connection_id,
                selected_data_types=(entry.data_type,),
                date_from=entry.date_from,
                date_to=entry.date_to,
                run_id=entry.run_id,
            )
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
        for connection_id, rows in normalized_by_connection.items():
            connection_entries = entries_by_connection[connection_id]
            replay_run_id = _replay_run_id(connection_entries)
            records = _deduplicate_normalized(rows)
            writer.save_events(run_id=replay_run_id, records=records)
            writer.compact_range(
                connection_id=connection_id,
                selected_data_types=tuple(
                    sorted({entry.data_type for entry in connection_entries})
                ),
                date_from=min(entry.date_from for entry in connection_entries),
                date_to=max(entry.date_to for entry in connection_entries),
                run_id=replay_run_id,
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
                entries.append(
                    RawReplayEntry(
                        key=key,
                        connection_id=values["connection_id"],
                        data_type=values["data_type"],
                        date_from=date.fromisoformat(values["date_from"]),
                        date_to=date.fromisoformat(values["date_to"]),
                        run_id=values["run_id"],
                    )
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"invalid_raw_google_health_key: {key}") from exc
    return sorted(
        entries,
        key=lambda item: (
            item.connection_id,
            item.data_type,
            item.date_from,
            item.date_to,
            item.run_id,
        ),
    )


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


def _append_normalized(
    rows: list[dict[str, Any]],
    normalized: dict[str, list[dict[str, Any]]],
) -> None:
    """connection単位のreplay用に正規化行を収集する。"""
    for dataset, dataset_rows in normalized.items():
        rows.extend({"_dataset": dataset, **row} for row in dataset_rows)


def _deduplicate_normalized(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Rawが重複期間を含む場合もrecord単位で一意にする。"""
    by_dataset: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
    for row in rows:
        dataset = str(row.pop("_dataset"))
        identity = (
            row.get("record_id"),
            row.get("metric_name"),
            row.get("date"),
            row.get("measured_at_utc"),
            row.get("started_at_utc"),
            row.get("ended_at_utc"),
            row.get("session_id"),
        )
        by_dataset.setdefault(dataset, {})[identity] = row
    result = {
        dataset: list(dataset_rows.values())
        for dataset, dataset_rows in by_dataset.items()
    }
    result["daily_metrics"] = aggregate_daily_metrics(result.get("daily_metrics", []))
    return result


def _replay_run_id(entries: list[RawReplayEntry]) -> str:
    identity = "|".join(entry.key for entry in entries)
    return f"raw-replay-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
