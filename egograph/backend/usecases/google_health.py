"""Google Health分析API/MCPのUseCase。"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from backend.domain.repositories.google_health import GoogleHealthRepositoryProtocol
from backend.validators import validate_date_range

MAX_RAW_TIMESERIES_ROWS = 1000
_RESOLUTION_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
_ALLOWED_RESOLUTIONS = {"auto", "raw", *_RESOLUTION_MINUTES}


class GetGoogleHealthDailySummaryUseCase:
    """指定期間のGoogle Health日次サマリを取得する。"""

    def __init__(self, repository: GoogleHealthRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        start_date: date | str,
        end_date: date | str,
    ) -> list[dict[str, Any]]:
        """日付範囲を検証して日次サマリを取得する。"""
        start, end = validate_date_range(start_date, end_date)
        return self._repository.get_daily_summary(start, end)


class GetGoogleHealthDailyMetricsUseCase:
    """指定期間の日次Projectionを取得する。"""

    def __init__(self, repository: GoogleHealthRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        start_date: date | str,
        end_date: date | str,
        data_type: str | None = None,
    ) -> dict[str, Any]:
        """日付範囲を検証し、metric単位のcolumnar結果を返す。"""
        start, end = validate_date_range(start_date, end_date)
        rows = self._repository.get_daily_metrics(start, end, data_type)
        return {
            "columns": ["date", "metric", "value", "unit"],
            "rows": [
                [
                    _iso_date(row["date"]),
                    row["metric_name"],
                    row["value"],
                    row["unit"],
                ]
                for row in rows
            ],
        }


class GetGoogleHealthTimeseriesUseCase:
    """Google Healthのsampleを時系列として取得する。"""

    def __init__(
        self,
        repository: GoogleHealthRepositoryProtocol,
        timezone: ZoneInfo | None = None,
    ) -> None:
        self._repository = repository
        self._timezone = timezone or ZoneInfo("UTC")

    def execute(
        self,
        data_type: str,
        start_at: datetime | str,
        end_at: datetime | str,
        resolution: str = "auto",
    ) -> dict[str, Any]:
        """時刻範囲と解像度を検証し、rawまたはbucket済み時系列を返す。"""
        if not isinstance(data_type, str) or not data_type.strip():
            raise ValueError("invalid_data_type: must not be empty")
        start = _parse_datetime(start_at, "start_at")
        end = _parse_datetime(end_at, "end_at")
        if start >= end:
            raise ValueError("invalid_timeseries: start_at must be before end_at")
        if resolution not in _ALLOWED_RESOLUTIONS:
            allowed = ", ".join(sorted(_ALLOWED_RESOLUTIONS))
            raise ValueError(f"invalid_resolution: must be one of: {allowed}")

        raw_rows = self._repository.get_timeseries(data_type, start, end)
        if resolution == "raw":
            if len(raw_rows) > MAX_RAW_TIMESERIES_ROWS:
                raise ValueError(
                    "invalid_timeseries: raw result exceeds 1000 rows; "
                    "request an aggregated resolution"
                )
            actual_resolution = "raw"
            series_rows = [_raw_series_row(row, self._timezone) for row in raw_rows]
        else:
            actual_resolution = (
                _choose_resolution(start, end) if resolution == "auto" else resolution
            )
            series_rows = _bucket_series_rows(
                raw_rows,
                minutes=_RESOLUTION_MINUTES[actual_resolution],
                timezone=self._timezone,
            )

        values = [float(row["value"]) for row in raw_rows]
        units = sorted({str(row["unit"]) for row in raw_rows if row.get("unit")})
        return {
            "type": data_type,
            "unit": units[0] if len(units) == 1 else None,
            "resolution": actual_resolution,
            "stats": _stats(values),
            "series": {
                "columns": (
                    ["time", "value"]
                    if actual_resolution == "raw"
                    else ["time", "avg", "min", "max"]
                ),
                "rows": series_rows,
            },
            "highlights": _highlights(raw_rows, self._timezone),
        }


class GetGoogleHealthSessionsUseCase:
    """指定期間のsleep/exercise sessionを取得する。"""

    def __init__(self, repository: GoogleHealthRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        start_date: date | str,
        end_date: date | str,
        data_type: str | None = None,
    ) -> dict[str, Any]:
        """日付範囲を検証し、sessionをcolumnar形式で返す。"""
        start, end = validate_date_range(start_date, end_date)
        rows = self._repository.get_sessions(start, end, data_type)
        columns = [
            "id",
            "type",
            "start",
            "end",
            "duration_s",
            "session_type",
        ]
        return {
            "columns": columns,
            "rows": [
                [
                    row["record_id"],
                    row["data_type"],
                    _iso_datetime(row["started_at_utc"]),
                    _iso_datetime(row["ended_at_utc"]),
                    row["duration_seconds"],
                    row["session_type"],
                ]
                for row in rows
            ],
        }


class GetGoogleHealthRecordUseCase:
    """完全保存されたGoogle Health recordを取得する。"""

    def __init__(self, repository: GoogleHealthRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, record_id: str) -> dict[str, Any]:
        """record_idを検証し、payload_jsonをJSONへ復元する。"""
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValueError("invalid_record_id: must not be empty")
        row = self._repository.get_record(record_id)
        if row is None:
            raise LookupError(f"google_health_record_not_found: {record_id}")
        try:
            payload = json.loads(row["payload_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "invalid_payload_json: stored payload is not valid JSON"
            ) from exc
        return {
            "id": row["record_id"],
            "type": row["data_type"],
            "kind": row["record_kind"],
            "date": _iso_date(row["record_date"]),
            "payload": payload,
        }


def _parse_datetime(value: datetime | str, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"invalid_{field_name}: must be ISO-8601 datetime"
            ) from exc
    else:
        raise ValueError(f"invalid_{field_name}: must be ISO-8601 datetime")
    if parsed.tzinfo is None:
        raise ValueError(f"invalid_{field_name}: timezone offset is required")
    return parsed.astimezone(UTC)


def _choose_resolution(start: datetime, end: datetime) -> str:
    seconds = (end - start).total_seconds()
    for resolution, minutes in _RESOLUTION_MINUTES.items():
        if seconds / (minutes * 60) <= 80:
            return resolution
    return "1h"


def _raw_series_row(row: dict[str, Any], timezone: ZoneInfo) -> list[Any]:
    return [
        _iso_datetime(row["measured_at_utc"], timezone),
        row["value"],
    ]


def _bucket_series_rows(
    rows: list[dict[str, Any]],
    *,
    minutes: int,
    timezone: ZoneInfo,
) -> list[list[Any]]:
    bucket_seconds = minutes * 60
    grouped: dict[tuple[datetime, str, str], list[float]] = {}
    for row in rows:
        measured_at = _as_utc_datetime(row["measured_at_utc"])
        local = measured_at.astimezone(timezone)
        bucket_epoch = math.floor(local.timestamp() / bucket_seconds) * bucket_seconds
        bucket = datetime.fromtimestamp(bucket_epoch, tz=timezone)
        key = (bucket, str(row["metric_name"]), str(row["unit"]))
        grouped.setdefault(key, []).append(float(row["value"]))
    return [
        [_iso_datetime(bucket, timezone), mean(values), min(values), max(values)]
        for (bucket, _metric_name, _unit), values in sorted(grouped.items())
    ]


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "min": None, "max": None}
    return {"avg": mean(values), "min": min(values), "max": max(values)}


def _highlights(
    rows: list[dict[str, Any]],
    timezone: ZoneInfo,
) -> dict[str, list[list[Any]]]:
    """局所ピークと10分窓の上昇・下降を少数の要点へ絞る。"""
    ordered = [
        (
            _as_utc_datetime(row["measured_at_utc"]),
            float(row["value"]),
            str(row["metric_name"]),
            str(row["unit"]),
        )
        for row in rows
    ]
    peaks = [
        ordered[index]
        for index in range(1, len(ordered) - 1)
        if ordered[index - 1][1] < ordered[index][1] > ordered[index + 1][1]
    ]
    changes: list[
        tuple[float, tuple[datetime, float, str, str], tuple[datetime, float, str, str]]
    ] = []
    window = timedelta(minutes=10)
    for index, current in enumerate(ordered):
        for previous in reversed(ordered[:index]):
            if current[0] - previous[0] > window:
                break
            if current[2] == previous[2] and current[3] == previous[3]:
                changes.append((current[1] - previous[1], previous, current))
                break
    rises = sorted(
        (item for item in changes if item[0] > 0),
        key=lambda item: item[0],
        reverse=True,
    )[:5]
    falls = sorted((item for item in changes if item[0] < 0), key=lambda item: item[0])[
        :5
    ]
    return {
        "peaks": [
            _highlight_point(item, timezone)
            for item in sorted(peaks, key=lambda item: item[1], reverse=True)[:5]
        ],
        "rises": [_change_point(item, timezone) for item in rises],
        "falls": [_change_point(item, timezone) for item in falls],
    }


def _highlight_point(
    item: tuple[datetime, float, str, str],
    timezone: ZoneInfo,
) -> list[Any]:
    return [_iso_datetime(item[0], timezone), item[1]]


def _change_point(
    item: tuple[
        float, tuple[datetime, float, str, str], tuple[datetime, float, str, str]
    ],
    timezone: ZoneInfo,
) -> list[Any]:
    delta, start, end = item
    return [
        _iso_datetime(start[0], timezone),
        _iso_datetime(end[0], timezone),
        start[1],
        end[1],
        delta,
    ]


def _as_utc_datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("invalid_timeseries: stored timestamp is invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _iso_datetime(value: Any, timezone: ZoneInfo | None = None) -> str:
    parsed = _as_utc_datetime(value) if isinstance(value, datetime) else value
    if not isinstance(parsed, datetime):
        return str(value)
    return parsed.astimezone(timezone or ZoneInfo("UTC")).isoformat()
