"""Google Health APIレスポンスの正規化。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pipelines.sources.google_health.data_types import (
    GoogleHealthDataType,
    RecordKind,
)
from pipelines.sources.google_health.projections import (
    MetricProjection,
    project_data_point,
)
from pipelines.sources.google_health.timezone import local_date


def normalize_google_health_payload(
    *,
    connection_id: str,
    data_type: GoogleHealthDataType,
    payload: dict[str, Any],
    raw_ref: str,
    ingested_at: datetime | None = None,
    timezone: ZoneInfo | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """APIレスポンスを完全保存recordと分析用Projectionへ変換する。"""
    ingested_at = ingested_at or datetime.now(tz=UTC)
    timezone = timezone or ZoneInfo("UTC")
    result: dict[str, list[dict[str, Any]]] = {
        "records": [],
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
                timezone=timezone,
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
                timezone=timezone,
            )

    for response in payload.get("dailyRollupResponses") or []:
        for point in response.get("rollupDataPoints", []):
            _normalize_data_point(
                result=result,
                connection_id=connection_id,
                data_type=data_type,
                point=point,
                raw_ref=raw_ref,
                ingested_at=ingested_at,
                timezone=timezone,
                daily_rollup=True,
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
    timezone: ZoneInfo,
    daily_rollup: bool = False,
) -> None:
    payload = _payload_for(point, data_type)
    source_record_id = _source_record_id(point)
    sample_time = _sample_time(payload, point)
    started_at, ended_at = _interval_times(payload, point)
    metric_date = _record_date(
        data_type,
        payload,
        point=point,
        sample_time=sample_time,
        started_at=started_at,
        ended_at=ended_at,
        timezone=timezone,
        daily_rollup=daily_rollup,
    )
    if metric_date is None:
        return

    record_id = _record_id(
        connection_id=connection_id,
        data_type=data_type,
        source_record_id=source_record_id,
        record_date=metric_date,
        sample_time=sample_time,
        started_at=started_at,
        ended_at=ended_at,
        payload=payload,
    )
    device_family = _device_family(point)
    result["records"].append(
        {
            "record_id": record_id,
            "source_record_id": source_record_id,
            "connection_id": connection_id,
            "data_type": data_type.name,
            "record_kind": data_type.record_kind.value,
            "record_date": metric_date,
            "payload_json": _canonical_json(payload),
            "device_family": device_family,
            "raw_ref": raw_ref,
            "ingested_at_utc": ingested_at,
        }
    )

    common = {
        "record_id": record_id,
        "connection_id": connection_id,
        "data_type": data_type.name,
        "device_family": device_family,
        "raw_ref": raw_ref,
        "ingested_at_utc": ingested_at,
    }

    if daily_rollup:
        _append_daily_projections(
            result["daily_metrics"],
            common=common,
            metric_date=metric_date,
            projections=project_data_point(data_type, payload),
        )
        return

    if data_type.record_kind is RecordKind.DAILY:
        _append_daily_projections(
            result["daily_metrics"],
            common=common,
            metric_date=metric_date,
            projections=project_data_point(data_type, payload),
        )
        return

    if data_type.record_kind is RecordKind.SAMPLE:
        if sample_time is None:
            return
        projections = project_data_point(data_type, payload)
        for projection in projections:
            result["samples"].append(
                {
                    **common,
                    "metric_name": projection.metric_name,
                    "measured_at_utc": sample_time,
                    "value": projection.value,
                    "unit": projection.unit,
                }
            )
        _append_respiratory_daily_projection(
            result["daily_metrics"],
            common=common,
            metric_date=metric_date,
            data_type=data_type,
            projections=projections,
        )
        return

    if started_at is None or ended_at is None:
        return

    if data_type.record_kind is RecordKind.INTERVAL:
        for projection in project_data_point(
            data_type,
            payload,
            started_at=started_at,
            ended_at=ended_at,
        ):
            result["intervals"].append(
                {
                    **common,
                    "metric_name": projection.metric_name,
                    "started_at_utc": started_at,
                    "ended_at_utc": ended_at,
                    "value": projection.value,
                    "unit": projection.unit,
                }
            )
        return

    duration_seconds = int((ended_at - started_at).total_seconds())
    result["sessions"].append(
        {
            **common,
            "session_id": source_record_id or record_id,
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "duration_seconds": duration_seconds,
            "session_type": _session_type(payload, data_type),
        }
    )
    result["daily_metrics"].append(
        {
            **common,
            "date": metric_date,
            "metric_name": (
                "sleep_duration" if data_type.name == "sleep" else "exercise_duration"
            ),
            "value": float(duration_seconds),
            "unit": "second",
        }
    )


def _append_daily_projections(
    rows: list[dict[str, Any]],
    *,
    common: dict[str, Any],
    metric_date: date,
    projections: list[MetricProjection],
) -> None:
    """日次Projectionを共通のParquet行へ変換する。"""
    for projection in projections:
        rows.append(
            {
                **common,
                "date": metric_date,
                "metric_name": projection.metric_name,
                "value": projection.value,
                "unit": projection.unit,
            }
        )


def _append_respiratory_daily_projection(
    rows: list[dict[str, Any]],
    *,
    common: dict[str, Any],
    metric_date: date,
    data_type: GoogleHealthDataType,
    projections: list[MetricProjection],
) -> None:
    """睡眠中呼吸数sampleの代表値を日次指標にも保存する。"""
    if data_type.name != "respiratory-rate-sleep-summary":
        return
    selected = next(
        (
            projection
            for projection in projections
            if projection.metric_name
            in {"full_sleep_respiratory_rate", "respiratory_rate"}
        ),
        None,
    )
    if selected is None:
        return
    rows.append(
        {
            **common,
            "date": metric_date,
            "metric_name": "respiratory_rate_sleep_summary",
            "value": selected.value,
            "unit": selected.unit,
        }
    )


def aggregate_daily_metrics(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """同一data type・日付・metric・単位の行を日次1行へまとめる。"""
    grouped: dict[tuple[str, str, date, str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    for row in rows:
        grouped[
            (
                row["connection_id"],
                row["data_type"],
                row["date"],
                row["metric_name"],
                row["unit"],
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
        aggregated.append({**latest, "value": value})
    return aggregated


def _payload_for(
    point: dict[str, Any],
    data_type: GoogleHealthDataType,
) -> dict[str, Any]:
    value = point.get(data_type.payload_name)
    return value if isinstance(value, dict) else point


def _source_record_id(point: dict[str, Any]) -> str | None:
    for key in ("dataPointName", "name"):
        value = point.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _record_date(
    data_type: GoogleHealthDataType,
    payload: dict[str, Any],
    *,
    point: dict[str, Any],
    sample_time: datetime | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    timezone: ZoneInfo,
    daily_rollup: bool = False,
) -> date | None:
    if daily_rollup:
        return _daily_date(point, payload)
    if data_type.record_kind is RecordKind.DAILY:
        return _daily_date(point, payload)
    if data_type.record_kind is RecordKind.SAMPLE:
        return (
            local_date(sample_time, timezone)
            if sample_time
            else _daily_date(point, payload)
        )
    if data_type.name == "sleep":
        return local_date(ended_at, timezone) if ended_at else None
    return local_date(started_at, timezone) if started_at else None


def _daily_date(point: dict[str, Any], payload: dict[str, Any]) -> date | None:
    raw_date = payload.get("date")
    if isinstance(raw_date, str):
        try:
            return date.fromisoformat(raw_date)
        except ValueError:
            return None
    if isinstance(raw_date, dict):
        return _civil_date(raw_date)
    civil_interval = point.get("civilTimeInterval")
    civil_start = point.get("civilStartTime")
    if civil_start is None and isinstance(civil_interval, dict):
        civil_start = civil_interval.get("startTime")
    if isinstance(civil_start, str):
        try:
            return date.fromisoformat(civil_start[:10])
        except ValueError:
            return None
    if isinstance(civil_start, dict):
        return _civil_date(civil_start.get("date", civil_start))
    return None


def _civil_date(value: dict[str, Any]) -> date | None:
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def _sample_time(
    payload: dict[str, Any],
    point: dict[str, Any],
) -> datetime | None:
    return _parse_datetime(
        _nested(payload, "sampleTime", "physicalTime") or point.get("instantTime")
    )


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
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _record_id(
    *,
    connection_id: str,
    data_type: GoogleHealthDataType,
    source_record_id: str | None,
    record_date: date,
    sample_time: datetime | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    payload: dict[str, Any],
) -> str:
    if source_record_id:
        identity = "|".join(
            (
                connection_id,
                data_type.name,
                data_type.record_kind.value,
                source_record_id,
            )
        )
    else:
        identity = "|".join(
            (
                connection_id,
                data_type.name,
                data_type.record_kind.value,
                record_date.isoformat(),
                _format_datetime(sample_time),
                _format_datetime(started_at),
                _format_datetime(ended_at),
                _canonical_json(payload),
            )
        )
    return f"rec_{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


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
