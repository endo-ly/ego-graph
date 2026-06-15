"""Google Health日次サマリ用DuckDBクエリ。"""

from datetime import date
from typing import Any

from backend.infrastructure.database.parquet_paths import build_dataset_glob
from backend.infrastructure.database.query_params import QueryParams


def _resolve_daily_metric_paths(params: QueryParams) -> list[str]:
    """存在するdaily_metricsから対象月のParquetだけを解決する。"""
    dataset_glob = build_dataset_glob(
        params.r2_config,
        data_domain="events",
        dataset_path="google_health/daily_metrics",
    )
    rows = params.conn.execute(
        "SELECT file FROM glob(?) ORDER BY file",
        (dataset_glob,),
    ).fetchall()
    target_months = set(_iter_months(params.start_date, params.end_date))
    return [
        str(row[0])
        for row in rows
        if any(
            f"/year={year}/month={month:02d}/" in str(row[0])
            for year, month in target_months
        )
    ]


def _iter_months(start_date: date, end_date: date):
    current = date(start_date.year, start_date.month, 1)
    limit = date(end_date.year, end_date.month, 1)
    while current <= limit:
        yield current.year, current.month
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )


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
                MAX(CASE WHEN data_type = 'steps' THEN value END) AS steps,
                MAX(CASE WHEN data_type = 'distance' THEN value END) AS distance,
                MAX(CASE
                    WHEN data_type = 'total-calories' THEN value
                END) AS total_calories,
                MAX(CASE
                    WHEN data_type = 'active-energy-burned' THEN value
                END) AS active_energy_burned,
                MAX(CASE
                    WHEN data_type = 'active-minutes' THEN value
                END) AS active_minutes,
                MAX(CASE
                    WHEN data_type = 'active-zone-minutes' THEN value
                END) AS active_zone_minutes,
                MAX(CASE
                    WHEN data_type = 'daily-resting-heart-rate' THEN value
                END) AS resting_heart_rate,
                MAX(CASE
                    WHEN data_type = 'daily-heart-rate-variability' THEN value
                END) AS daily_hrv,
                MAX(CASE
                    WHEN data_type = 'daily-oxygen-saturation' THEN value
                END) AS daily_oxygen_saturation,
                MAX(CASE
                    WHEN data_type IN (
                        'daily-respiratory-rate',
                        'respiratory-rate-sleep-summary'
                    ) THEN value
                END) AS daily_respiratory_rate,
                MAX(CASE
                    WHEN data_type = 'sleep' THEN value
                END) AS sleep_duration,
                MAX(CASE
                    WHEN data_type = 'daily-vo2-max' THEN value
                END) AS daily_vo2_max
            FROM read_parquet(?, union_by_name = true)
            WHERE date >= ? AND date <= ?
            GROUP BY date
        )
        SELECT *
        FROM google_health_daily_summary
        ORDER BY date ASC
        """,
        (
            paths,
            params.start_date,
            params.end_date,
        ),
    )
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
