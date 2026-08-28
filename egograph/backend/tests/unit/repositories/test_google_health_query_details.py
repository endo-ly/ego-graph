"""Google Health詳細QueryのDuckDBテスト。"""

from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
from dataset_catalog import datasets

from backend.infrastructure.database.google_health_queries import (
    GoogleHealthQueryParams,
    _resolve_all_paths,
    get_daily_metrics,
    get_record,
    get_sessions,
    get_timeseries_rows,
)
from backend.validators import to_utc_range


def _write_dataset(root: Path, dataset: str, rows: list[dict]) -> None:
    path = root / "compacted" / "events" / "google_health" / dataset
    path = path / "year=2026" / "month=06"
    path.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(path / "data.parquet")


def test_detail_queries_filter_and_return_full_record(
    duckdb_conn,
    mock_r2_config,
    tmp_path,
):
    """日次・時系列・session・recordの4 queryが新schemaを読む。"""
    # Arrange
    _write_dataset(
        tmp_path,
        "daily_metrics",
        [
            {
                "date": date(2026, 6, 1),
                "data_type": "daily-heart-rate-variability",
                "metric_name": "rmssd",
                "value": 48.3,
                "unit": "millisecond",
            },
            {
                "date": date(2026, 6, 1),
                "data_type": "steps",
                "metric_name": "steps",
                "value": 8000.0,
                "unit": "count",
            },
        ],
    )
    _write_dataset(
        tmp_path,
        "samples",
        [
            {
                "record_id": "rec-1",
                "data_type": "heart-rate",
                "metric_name": "heart_rate",
                "measured_at_utc": datetime(2026, 6, 1, 0, 1),
                "value": 70.0,
                "unit": "beats_per_minute",
            }
        ],
    )
    _write_dataset(
        tmp_path,
        "intervals",
        [
            {
                "record_id": "rec-steps",
                "data_type": "steps",
                "metric_name": "steps",
                "started_at_utc": datetime(2026, 6, 1, 0, 2),
                "ended_at_utc": datetime(2026, 6, 1, 0, 5),
                "value": 120.0,
                "unit": "count",
            }
        ],
    )
    _write_dataset(
        tmp_path,
        "sessions",
        [
            {
                "record_id": "rec-sleep",
                "data_type": "sleep",
                "session_id": "sleep-1",
                "started_at_utc": datetime(2026, 5, 31, 23),
                "ended_at_utc": datetime(2026, 6, 1, 7),
                "duration_seconds": 28800,
                "session_type": "sleep",
                "device_family": "fitbit_air",
                "raw_ref": "raw/x",
            }
        ],
    )
    _write_dataset(
        tmp_path,
        "records",
        [
            {
                "record_id": "rec-1",
                "source_record_id": None,
                "connection_id": "connection-1",
                "data_type": "heart-rate",
                "record_kind": "sample",
                "record_date": date(2026, 6, 1),
                "payload_json": '{"beatsPerMinute":70,"future":true}',
                "device_family": "fitbit_air",
                "raw_ref": "raw/x",
                "ingested_at_utc": datetime(2026, 6, 2),
            }
        ],
    )
    mock_r2_config.local_parquet_root = str(tmp_path)
    utc_start, utc_end = to_utc_range(
        date(2026, 6, 1), date(2026, 6, 1), ZoneInfo("UTC")
    )
    params = GoogleHealthQueryParams(
        conn=duckdb_conn,
        r2_config=mock_r2_config,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        utc_start=utc_start,
        utc_end=utc_end,
        tz_name="UTC",
    )

    # Act
    daily = get_daily_metrics(params, data_type="steps")
    samples = get_timeseries_rows(
        params,
        data_type="heart-rate",
        start_at_utc=datetime(2026, 6, 1),
        end_at_utc=datetime(2026, 6, 2),
    )
    intervals = get_timeseries_rows(
        params,
        data_type="steps",
        start_at_utc=datetime(2026, 6, 1),
        end_at_utc=datetime(2026, 6, 2),
    )
    sessions = get_sessions(params, data_type="sleep")
    record_path = (
        tmp_path
        / "compacted"
        / "events"
        / "google_health"
        / "records"
        / "year=2026"
        / "month=06"
        / "data.parquet"
    )
    with patch(
        "backend.infrastructure.database.google_health_queries._resolve_all_paths",
        return_value=[str(record_path)],
    ):
        record = get_record(params, "rec-1")

    # Assert
    assert daily[0]["metric_name"] == "steps"
    assert len(samples) == 1
    assert intervals[0]["measured_at_utc"] == datetime(2026, 6, 1, 0, 2)
    assert sessions[0]["record_id"] == "rec-sleep"
    assert record is not None
    assert record["payload_json"] == '{"beatsPerMinute":70,"future":true}'


def test_record_paths_always_use_r2_glob_even_when_local_mirror_exists(
    mock_r2_config,
    tmp_path,
    duckdb_conn,
):
    """全件record lookupは不完全なLocal mirrorを使わない。"""
    mock_r2_config.local_parquet_root = str(tmp_path)
    params = GoogleHealthQueryParams(
        conn=duckdb_conn,
        r2_config=mock_r2_config,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        utc_start=datetime(2026, 6, 1),
        utc_end=datetime(2026, 6, 2),
        tz_name="UTC",
    )

    result = _resolve_all_paths(params, datasets.GOOGLE_HEALTH_RECORDS)

    assert result == [
        "s3://test-bucket/compacted/events/google_health/records/**/*.parquet"
    ]
