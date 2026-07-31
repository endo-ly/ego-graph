"""Google Health DuckDBクエリのテスト。"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pandas as pd

from backend.infrastructure.database.google_health_queries import (
    _resolve_daily_metric_paths,
    get_daily_summary,
)
from backend.infrastructure.database.query_params import QueryParams
from backend.validators import to_utc_range


def test_get_daily_summary_pivots_metrics_and_preserves_missing_values(
    duckdb_conn,
    mock_r2_config,
    tmp_path,
):
    """日次指標を1日1行へ集約し、欠損指標をNULLで返す。"""
    local_root = tmp_path / "mirror"
    daily_dir = (
        local_root
        / "compacted"
        / "events"
        / "google_health"
        / "daily_metrics"
        / "year=2026"
        / "month=06"
    )
    daily_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "connection_id": "google-health-primary",
                "data_type": "steps",
                "date": date(2026, 6, 1),
                "metric_name": "steps",
                "value": 8000.0,
                "unit": "count",
            },
            {
                "connection_id": "google-health-primary",
                "data_type": "sleep",
                "date": date(2026, 6, 1),
                "metric_name": "sleep_duration",
                "value": 25200.0,
                "unit": "second",
            },
            {
                "connection_id": "google-health-primary",
                "data_type": "sleep",
                "date": date(2026, 6, 1),
                "metric_name": "sleep_score",
                "value": 99999.0,
                "unit": "point",
            },
            {
                "connection_id": "google-health-primary",
                "data_type": "future-hrv-source",
                "date": date(2026, 6, 2),
                "metric_name": "daily_heart_rate_variability",
                "value": 42.0,
                "unit": "millisecond",
            },
        ]
    ).to_parquet(daily_dir / "data.parquet")
    mock_r2_config.local_parquet_root = str(local_root)
    utc_start, utc_end = to_utc_range(
        date(2026, 6, 1),
        date(2026, 6, 2),
        timezone.utc,
    )
    params = QueryParams(
        conn=duckdb_conn,
        r2_config=mock_r2_config,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        utc_start=utc_start,
        utc_end=utc_end,
    )

    result = get_daily_summary(params)

    assert len(result) == 2
    assert result[0]["date"] == date(2026, 6, 1)
    assert result[0]["steps"] == 8000.0
    assert result[0]["sleep_duration"] == 25200.0
    assert result[0]["daily_hrv"] is None
    assert result[1]["date"] == date(2026, 6, 2)
    assert result[1]["daily_hrv"] == 42.0


def test_daily_metric_paths_use_r2_for_all_partitions_when_local_is_partial(
    mock_r2_config,
    tmp_path,
):
    """Local partitionが欠ける場合は全partitionをR2から解決する。"""
    local_root = tmp_path / "mirror"
    local_partition = (
        local_root
        / "compacted"
        / "events"
        / "google_health"
        / "daily_metrics"
        / "year=2026"
        / "month=06"
    )
    local_partition.mkdir(parents=True)
    (local_partition / "data.parquet").write_bytes(b"local")
    mock_r2_config.local_parquet_root = str(local_root)

    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [
            (
                "s3://test-bucket/compacted/events/google_health/"
                "daily_metrics/year=2026/month=06/data.parquet",
            )
        ],
        [],
    ]
    params = QueryParams(
        conn=conn,
        r2_config=mock_r2_config,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        utc_start=datetime(2026, 6, 1),
        utc_end=datetime(2026, 7, 1),
    )

    result = _resolve_daily_metric_paths(params)

    assert result == [
        "s3://test-bucket/compacted/events/google_health/"
        "daily_metrics/year=2026/month=06/data.parquet"
    ]
    assert conn.execute.call_count == 2


def test_get_daily_summary_maps_compacted_metric_names(
    duckdb_conn,
    mock_r2_config,
    tmp_path,
):
    """実際のmetric_nameをdaily_hrv/daily_oxygen_saturationへ射影する。"""
    local_root = tmp_path / "mirror"
    daily_dir = (
        local_root
        / "compacted"
        / "events"
        / "google_health"
        / "daily_metrics"
        / "year=2026"
        / "month=06"
    )
    daily_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "connection_id": "google-health-primary",
                "data_type": "heart_rate_variability",
                "date": date(2026, 6, 1),
                "metric_name": (
                    "daily_heart_rate_variability_average_"
                    "heart_rate_variability_milliseconds"
                ),
                "value": 48.0,
                "unit": "millisecond",
            },
            {
                "connection_id": "google-health-primary",
                "data_type": "oxygen_saturation",
                "date": date(2026, 6, 1),
                "metric_name": "daily_oxygen_saturation_average_percentage",
                "value": 97.0,
                "unit": "percentage",
            },
        ]
    ).to_parquet(daily_dir / "data.parquet")
    mock_r2_config.local_parquet_root = str(local_root)
    utc_start, utc_end = to_utc_range(
        date(2026, 6, 1),
        date(2026, 6, 1),
        timezone.utc,
    )
    params = QueryParams(
        conn=duckdb_conn,
        r2_config=mock_r2_config,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        utc_start=utc_start,
        utc_end=utc_end,
    )

    result = get_daily_summary(params)

    assert len(result) == 1
    assert result[0]["date"] == date(2026, 6, 1)
    assert result[0]["daily_hrv"] == 48.0
    assert result[0]["daily_oxygen_saturation"] == 97.0


def test_get_daily_summary_returns_empty_when_partition_is_missing(
    mock_r2_config,
    tmp_path,
):
    """対象月のParquetがない場合は取得失敗ではなく空配列を返す。"""
    local_root = tmp_path / "mirror"
    other_month = (
        local_root
        / "compacted"
        / "events"
        / "google_health"
        / "daily_metrics"
        / "year=2026"
        / "month=05"
    )
    other_month.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": [date(2026, 5, 1)],
            "data_type": ["steps"],
            "value": [100.0],
        }
    ).to_parquet(other_month / "data.parquet")
    mock_r2_config.local_parquet_root = str(local_root)
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    utc_start, utc_end = to_utc_range(
        date(2026, 6, 1),
        date(2026, 6, 30),
        timezone.utc,
    )
    params = QueryParams(
        conn=conn,
        r2_config=mock_r2_config,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        utc_start=utc_start,
        utc_end=utc_end,
    )

    result = get_daily_summary(params)

    assert result == []
    assert conn.execute.call_count == 2
