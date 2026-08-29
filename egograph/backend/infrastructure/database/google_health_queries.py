"""Google Health compacted Parquet用DuckDBクエリ。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dataset_catalog import DatasetDefinition, datasets
from pipelines.sources.google_health.data_types import DATA_TYPE_BY_NAME, RecordKind

from backend.config import R2Config
from backend.infrastructure.database.parquet_paths import (
    build_dataset_glob,
    build_partition_paths,
)
from backend.infrastructure.database.query_params import QueryParams


@dataclass(frozen=True)
class GoogleHealthQueryParams:
    """Google Healthクエリに共通するDuckDB接続と期間。"""

    conn: Any
    r2_config: R2Config
    start_date: date
    end_date: date
    utc_start: datetime
    utc_end: datetime
    tz_name: str


def _resolve_partition_paths(
    params: GoogleHealthQueryParams | QueryParams,
    dataset: DatasetDefinition,
) -> list[str]:
    """対象月のParquet実体を解決する。"""
    partition_paths = build_partition_paths(
        params.r2_config,
        dataset,
        params.utc_start,
        params.utc_end,
    )
    resolved_paths: list[str] = []
    for path in partition_paths:
        if not path.startswith("s3://"):
            if Path(path).exists():
                resolved_paths.append(path)
            continue
        rows = params.conn.execute(
            "SELECT file FROM glob(?) ORDER BY file",
            (f"{path.rsplit('/', 1)[0]}/*.parquet",),
        ).fetchall()
        resolved_paths.extend(str(row[0]) for row in rows)
    return resolved_paths


def _resolve_daily_metric_paths(params: QueryParams) -> list[str]:
    """対象期間のdaily_metrics Parquetを単一sourceから解決する。"""
    return _resolve_partition_paths(params, datasets.GOOGLE_HEALTH_DAILY_METRICS)


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def get_daily_summary(params: QueryParams) -> list[dict[str, Any]]:
    """指定期間のGoogle Health日次サマリを返す。"""
    paths = _resolve_daily_metric_paths(params)
    if not paths:
        return []
    cursor = params.conn.execute(
        """
        WITH google_health_daily_summary AS (
            SELECT
                date,
                MAX(CASE WHEN metric_name = 'steps' THEN value END) AS steps,
                MAX(CASE WHEN metric_name = 'distance' THEN value END) AS distance,
                MAX(CASE WHEN metric_name = 'total_calories' THEN value END)
                    AS total_calories,
                MAX(CASE WHEN metric_name = 'active_energy_burned' THEN value END)
                    AS active_energy_burned,
                MAX(CASE WHEN metric_name = 'active_minutes' THEN value END)
                    AS active_minutes,
                MAX(CASE WHEN metric_name = 'active_zone_minutes' THEN value END)
                    AS active_zone_minutes,
                MAX(CASE WHEN metric_name = 'resting_heart_rate' THEN value END)
                    AS resting_heart_rate,
                MAX(CASE WHEN metric_name = 'daily_hrv' THEN value END) AS daily_hrv,
                MAX(CASE WHEN metric_name = 'daily_oxygen_saturation' THEN value END)
                    AS daily_oxygen_saturation,
                MAX(CASE WHEN metric_name IN (
                    'daily_respiratory_rate',
                    'respiratory_rate_sleep_summary'
                ) THEN value END) AS daily_respiratory_rate,
                MAX(CASE WHEN metric_name = 'sleep_duration' THEN value END)
                    AS sleep_duration,
                MAX(CASE WHEN metric_name = 'daily_vo2_max' THEN value END)
                    AS daily_vo2_max
            FROM read_parquet(?, union_by_name = true)
            WHERE date >= ? AND date <= ?
            GROUP BY date
        )
        SELECT *
        FROM google_health_daily_summary
        ORDER BY date ASC
        """,
        (paths, params.start_date, params.end_date),
    )
    return _rows(cursor)


def get_daily_metrics(
    params: GoogleHealthQueryParams,
    data_type: str | None = None,
) -> list[dict[str, Any]]:
    """日次Projectionをmetric単位の行で返す。"""
    paths = _resolve_partition_paths(params, datasets.GOOGLE_HEALTH_DAILY_METRICS)
    if not paths:
        return []
    sql = """
        SELECT date, data_type, metric_name, value, unit
        FROM read_parquet(?, union_by_name = true)
        WHERE date >= ? AND date <= ?
    """
    query_params: list[Any] = [paths, params.start_date, params.end_date]
    if data_type is not None:
        sql += " AND data_type = ?"
        query_params.append(data_type)
    sql += " ORDER BY date ASC, data_type ASC, metric_name ASC"
    return _rows(params.conn.execute(sql, tuple(query_params)))


def get_timeseries_rows(
    params: GoogleHealthQueryParams,
    *,
    data_type: str,
    start_at_utc: datetime,
    end_at_utc: datetime,
    metric: str | None = None,
) -> list[dict[str, Any]]:
    """指定data typeのsampleまたはintervalを時刻順で返す。"""
    dataset, time_column = _timeseries_dataset(data_type)
    paths = _resolve_partition_paths(params, dataset)
    if not paths:
        return []
    sql = f"""
        SELECT {time_column} AS measured_at_utc, metric_name, value, unit
        FROM read_parquet(?, union_by_name = true)
        WHERE data_type = ?
          AND {time_column} >= ?
          AND {time_column} < ?
    """
    query_params: list[Any] = [paths, data_type, start_at_utc, end_at_utc]
    if metric is not None:
        sql += " AND metric_name = ?"
        query_params.append(metric)
    sql += f" ORDER BY {time_column} ASC, metric_name ASC"
    return _rows(params.conn.execute(sql, tuple(query_params)))


def _timeseries_dataset(
    data_type: str,
) -> tuple[DatasetDefinition, str]:
    """Registryからdata typeのProjection datasetと時刻列を解決する。"""
    definition = DATA_TYPE_BY_NAME.get(data_type)
    if definition is None:
        raise ValueError(
            f"invalid_data_type: unsupported Google Health data type: {data_type}"
        )
    if definition.record_kind is RecordKind.SAMPLE:
        return datasets.GOOGLE_HEALTH_SAMPLES, "measured_at_utc"
    if definition.record_kind is RecordKind.INTERVAL:
        return datasets.GOOGLE_HEALTH_INTERVALS, "started_at_utc"
    raise ValueError(
        f"invalid_data_type: data type has no timeseries projection: {data_type}"
    )


def get_sessions(
    params: GoogleHealthQueryParams,
    data_type: str | None = None,
) -> list[dict[str, Any]]:
    """指定期間のsessionを開始・終了時刻付きで返す。"""
    paths = _resolve_partition_paths(params, datasets.GOOGLE_HEALTH_SESSIONS)
    if not paths:
        return []
    sql = """
        SELECT
            record_id,
            data_type,
            session_id,
            started_at_utc,
            ended_at_utc,
            duration_seconds,
            session_type,
            device_family,
            raw_ref
        FROM read_parquet(?, union_by_name = true)
        WHERE CASE
            WHEN data_type = 'sleep' THEN ended_at_utc
            ELSE started_at_utc
        END >= ?
          AND CASE
            WHEN data_type = 'sleep' THEN ended_at_utc
            ELSE started_at_utc
        END < ?
    """
    query_params: list[Any] = [paths, params.utc_start, params.utc_end]
    if data_type is not None:
        sql += " AND data_type = ?"
        query_params.append(data_type)
    sql += " ORDER BY started_at_utc ASC, record_id ASC"
    return _rows(params.conn.execute(sql, tuple(query_params)))


def _resolve_all_paths(
    params: GoogleHealthQueryParams,
    dataset: DatasetDefinition,
) -> list[str]:
    """dataset全体検索用のParquet pathを解決する。"""
    # Local mirrorは完全性を保証しないため、期間なしのrecord lookupは常に
    # 正本のR2 globを使う。
    return [build_dataset_glob(params.r2_config, dataset)]


def get_record(
    params: GoogleHealthQueryParams,
    record_id: str,
) -> dict[str, Any] | None:
    """record_idで完全保存recordを1件取得する。"""
    paths = _resolve_all_paths(params, datasets.GOOGLE_HEALTH_RECORDS)
    if not paths:
        return None
    cursor = params.conn.execute(
        """
        SELECT
            record_id,
            source_record_id,
            connection_id,
            data_type,
            record_kind,
            record_date,
            payload_json,
            device_family,
            raw_ref,
            ingested_at_utc
        FROM read_parquet(?, union_by_name = true)
        WHERE record_id = ?
        LIMIT 1
        """,
        (paths, record_id),
    )
    rows = _rows(cursor)
    return rows[0] if rows else None
