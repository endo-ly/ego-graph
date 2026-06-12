"""Google Health APIレスポンスの正規化。"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from pipelines.sources.google_health.data_types import (
    GoogleHealthDataType,
    RecordKind,
)

_DURATION_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?s$")
_IGNORED_NUMERIC_PATH_PARTS = {
    "year",
    "month",
    "day",
    "hours",
    "minutes",
    "seconds",
    "nanos",
}
_ACTIVITY_LEVEL_VALUES = {
    "ACTIVITY_LEVEL_TYPE_UNSPECIFIED": 0.0,
    "SEDENTARY": 1.0,
    "LIGHT": 2.0,
    "MODERATE": 3.0,
    "VIGOROUS": 4.0,
}


def normalize_google_health_payload(
    *,
    connection_id: str,
    data_type: GoogleHealthDataType,
    payload: dict[str, Any],
    raw_ref: str,
    ingested_at: datetime | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """APIレスポンス原本を4種類のParquet行へ変換する。"""
    ingested_at = ingested_at or datetime.now(tz=UTC)
    result: dict[str, list[dict[str, Any]]] = {
        "daily_metrics": [],
        "samples": [],
        "intervals": [],
        "sessions": [],
    }

    for response in payload.get("reconcileResponses") or []:
        for point in response.get("dataPoints", []):
            _normalize_data_point(
                result=result,
                connection_id=connection_id,
                data_type=data_type,
                point=point,
                raw_ref=raw_ref,
                ingested_at=ingested_at,
            )

    for response in payload.get("rollupResponses") or []:
        for point in response.get("rollupDataPoints", []):
            _normalize_data_point(
                result=result,
                connection_id=connection_id,
                data_type=data_type,
                point=point,
                raw_ref=raw_ref,
                ingested_at=ingested_at,
            )

    for response in payload.get("dailyRollupResponses") or []:
        for point in response.get("rollupDataPoints", []):
            _append_daily_metrics(
                result["daily_metrics"],
                connection_id=connection_id,
                data_type=data_type,
                point=point,
                raw_ref=raw_ref,
                ingested_at=ingested_at,
            )
    return result


def _normalize_data_point(
    *,
    result: dict[str, list[dict[str, Any]]],
    connection_id: str,
    data_type: GoogleHealthDataType,
    point: dict[str, Any],
    raw_ref: str,
    ingested_at: datetime,
) -> None:
    payload = _payload_for(point, data_type)
    device_family = _device_family(point)
    common = {
        "connection_id": connection_id,
        "data_type": data_type.name,
        "device_family": device_family,
        "raw_ref": raw_ref,
        "ingested_at_utc": ingested_at,
    }

    if data_type.record_kind is RecordKind.DAILY:
        _append_daily_metrics(
            result["daily_metrics"],
            connection_id=connection_id,
            data_type=data_type,
            point=point,
            raw_ref=raw_ref,
            ingested_at=ingested_at,
        )
        return

    if data_type.record_kind is RecordKind.SAMPLE:
        measured_at = _parse_datetime(
            _nested(payload, "sampleTime", "physicalTime") or point.get("instantTime")
        )
        value = _first_numeric_value(payload)
        if measured_at is not None and value is not None:
            result["samples"].append(
                {
                    **common,
                    "measured_at_utc": measured_at,
                    "value": value,
                    "unit": data_type.unit,
                }
            )
            if data_type.name == "respiratory-rate-sleep-summary":
                result["daily_metrics"].append(
                    {
                        "connection_id": connection_id,
                        "data_type": data_type.name,
                        "date": measured_at.date(),
                        "metric_name": "respiratory_rate_sleep_summary",
                        "value": value,
                        "unit": data_type.unit,
                        "device_family": device_family,
                        "raw_ref": raw_ref,
                        "ingested_at_utc": ingested_at,
                    }
                )
        return

    started_at, ended_at = _interval_times(payload, point)
    if started_at is None or ended_at is None:
        return

    if data_type.record_kind is RecordKind.INTERVAL:
        value = _interval_value(
            payload,
            data_type=data_type,
            started_at=started_at,
            ended_at=ended_at,
        )
        if value is not None:
            result["intervals"].append(
                {
                    **common,
                    "started_at_utc": started_at,
                    "ended_at_utc": ended_at,
                    "value": value,
                    "unit": data_type.unit,
                }
            )
        return

    duration_seconds = int((ended_at - started_at).total_seconds())
    result["sessions"].append(
        {
            **common,
            "session_id": str(point.get("dataPointName") or point.get("name") or ""),
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "duration_seconds": duration_seconds,
            "session_type": _session_type(payload, data_type),
        }
    )
    result["daily_metrics"].append(
        {
            "connection_id": connection_id,
            "data_type": data_type.name,
            "date": ended_at.date() if data_type.name == "sleep" else started_at.date(),
            "metric_name": (
                "sleep_duration" if data_type.name == "sleep" else "exercise_duration"
            ),
            "value": float(duration_seconds),
            "unit": "second",
            "device_family": device_family,
            "raw_ref": raw_ref,
            "ingested_at_utc": ingested_at,
        }
    )


def _append_daily_metrics(
    rows: list[dict[str, Any]],
    *,
    connection_id: str,
    data_type: GoogleHealthDataType,
    point: dict[str, Any],
    raw_ref: str,
    ingested_at: datetime,
) -> None:
    payload = _payload_for(point, data_type)
    metric_date = _daily_date(point, payload)
    if metric_date is None:
        return
    values = list(_numeric_leaves(payload))
    if not values:
        return
    device_family = _device_family(point)
    base_name = data_type.name.replace("-", "_")
    for path, value in values:
        suffix = "_".join(_snake_case(part) for part in path)
        metric_name = base_name if len(values) == 1 else f"{base_name}_{suffix}"
        rows.append(
            {
                "connection_id": connection_id,
                "data_type": data_type.name,
                "date": metric_date,
                "metric_name": metric_name,
                "value": value,
                "unit": data_type.unit,
                "device_family": device_family,
                "raw_ref": raw_ref,
                "ingested_at_utc": ingested_at,
            }
        )


def aggregate_daily_metrics(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """同一data type・日付・metricの行を合算して日次1行へまとめる。"""
    grouped: dict[tuple[str, str, date, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row["connection_id"],
                row["data_type"],
                row["date"],
                row["metric_name"],
            )
        ].append(row)

    aggregated: list[dict[str, Any]] = []
    for group in grouped.values():
        latest = max(group, key=lambda item: item["ingested_at_utc"])
        values = [float(item["value"]) for item in group]
        value = (
            sum(values) / len(values)
            if latest["data_type"] == "respiratory-rate-sleep-summary"
            else sum(values)
        )
        aggregated.append(
            {
                **latest,
                "value": value,
            }
        )
    return aggregated


def _payload_for(
    point: dict[str, Any],
    data_type: GoogleHealthDataType,
) -> dict[str, Any]:
    value = point.get(data_type.payload_name)
    return value if isinstance(value, dict) else point


def _daily_date(point: dict[str, Any], payload: dict[str, Any]) -> date | None:
    raw_date = payload.get("date")
    if isinstance(raw_date, str):
        return date.fromisoformat(raw_date)
    if isinstance(raw_date, dict):
        return _civil_date(raw_date)
    civil_start = point.get("civilStartTime") or point.get("civilTimeInterval", {}).get(
        "startTime"
    )
    if isinstance(civil_start, str):
        return date.fromisoformat(civil_start[:10])
    if isinstance(civil_start, dict):
        return _civil_date(civil_start.get("date", civil_start))
    return None


def _civil_date(value: dict[str, Any]) -> date | None:
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def _interval_times(
    payload: dict[str, Any],
    point: dict[str, Any],
) -> tuple[datetime | None, datetime | None]:
    interval = payload.get("interval") or point.get("interval") or {}
    if not isinstance(interval, dict):
        interval = {}
    return (
        _parse_datetime(interval.get("startTime") or point.get("startTime")),
        _parse_datetime(interval.get("endTime") or point.get("endTime")),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _first_numeric_value(payload: dict[str, Any]) -> float | None:
    return next((value for _, value in _numeric_leaves(payload)), None)


def _interval_value(
    payload: dict[str, Any],
    *,
    data_type: GoogleHealthDataType,
    started_at: datetime,
    ended_at: datetime,
) -> float | None:
    value = _first_numeric_value(payload)
    if value is not None:
        return value
    if data_type.name in {"sedentary-period", "time-in-heart-rate-zone"}:
        return (ended_at - started_at).total_seconds()
    if data_type.name == "activity-level":
        raw_level = payload.get("activityLevelType") or payload.get("activityLevel")
        if isinstance(raw_level, str):
            return _ACTIVITY_LEVEL_VALUES.get(raw_level.upper())
    return None


def _numeric_leaves(
    value: Any,
    path: tuple[str, ...] = (),
):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not path or path[-1] not in _IGNORED_NUMERIC_PATH_PARTS:
            yield path, float(value)
        return
    if isinstance(value, str):
        try:
            parsed = (
                float(value[:-1]) if _DURATION_PATTERN.match(value) else float(value)
            )
        except ValueError:
            return
        if not path or path[-1] not in _IGNORED_NUMERIC_PATH_PARTS:
            yield path, parsed
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"interval", "sampleTime", "date"}:
                continue
            yield from _numeric_leaves(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _numeric_leaves(item, (*path, str(index)))


def _nested(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _device_family(point: dict[str, Any]) -> str:
    data_source = point.get("dataSource") or point.get("dataOrigin") or {}
    text = str(data_source).lower()
    return "fitbit_air" if "fitbit" in text or "google-wearables" in text else "unknown"


def _session_type(
    payload: dict[str, Any],
    data_type: GoogleHealthDataType,
) -> str:
    value = payload.get("type") or payload.get("exerciseType")
    return str(value).lower() if value else data_type.name


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
