"""Google Health詳細Query UseCaseのテスト。"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from backend.usecases.google_health import (
    GetGoogleHealthDailyMetricsUseCase,
    GetGoogleHealthRecordUseCase,
    GetGoogleHealthSessionsUseCase,
    GetGoogleHealthTimeseriesUseCase,
)


class FakeGoogleHealthQueryRepository:
    """詳細Query UseCase用のRepository fake。"""

    def __init__(self) -> None:
        self.timeseries_calls: list[tuple[str, datetime, datetime, str | None]] = []

    def get_daily_metrics(self, start_date, end_date, data_type=None):
        return [
            {
                "date": date(2026, 6, 1),
                "data_type": data_type or "daily-heart-rate-variability",
                "metric_name": "hrv_rmssd",
                "value": 48.3,
                "unit": "ms",
                "connection_id": "hidden",
            }
        ]

    def get_timeseries(self, data_type, start_at, end_at, metric=None):
        self.timeseries_calls.append((data_type, start_at, end_at, metric))
        return [
            {
                "measured_at_utc": datetime(2026, 6, 1, 0, 0),
                "metric_name": "heart_rate",
                "value": 60.0,
                "unit": "bpm",
            },
            {
                "measured_at_utc": datetime(2026, 6, 1, 0, 4),
                "metric_name": "heart_rate",
                "value": 80.0,
                "unit": "bpm",
            },
            {
                "measured_at_utc": datetime(2026, 6, 1, 0, 8),
                "metric_name": "heart_rate",
                "value": 70.0,
                "unit": "bpm",
            },
        ]

    def get_sessions(self, start_date, end_date, data_type=None):
        return [
            {
                "record_id": "rec-sleep",
                "data_type": data_type or "sleep",
                "session_id": "sleep-1",
                "started_at_utc": datetime(2026, 5, 31, 23),
                "ended_at_utc": datetime(2026, 6, 1, 7),
                "duration_seconds": 28800,
                "session_type": "sleep",
            }
        ]

    def get_record(self, record_id):
        return {
            "record_id": record_id,
            "source_record_id": "source-1",
            "connection_id": "hidden",
            "data_type": "sleep",
            "record_kind": "session",
            "record_date": date(2026, 6, 1),
            "payload_json": '{"type":"SLEEP","unknown":true}',
            "device_family": "fitbit_air",
            "raw_ref": "hidden",
            "ingested_at_utc": datetime(2026, 6, 2),
        }


def test_daily_metrics_returns_compact_columnar_shape():
    """日次結果は内部metadataを含めずcolumnar形式で返す。"""
    # Arrange
    use_case = GetGoogleHealthDailyMetricsUseCase(FakeGoogleHealthQueryRepository())

    # Act
    result = use_case.execute("2026-06-01", "2026-06-01")

    # Assert
    assert result == {
        "columns": ["date", "metric", "value", "unit"],
        "rows": [["2026-06-01", "hrv_rmssd", 48.3, "ms"]],
    }


def test_timeseries_aggregates_and_uses_configured_timezone():
    """時系列はbucket統計と設定TZの時刻を返す。"""
    # Arrange
    repository = FakeGoogleHealthQueryRepository()
    use_case = GetGoogleHealthTimeseriesUseCase(
        repository,
        timezone=ZoneInfo("Asia/Tokyo"),
    )

    # Act
    result = use_case.execute(
        "heart-rate",
        "2026-06-01T00:00:00+00:00",
        "2026-06-01T00:12:00+00:00",
        "5m",
    )

    # Assert
    assert result["type"] == "heart-rate"
    assert result["stats"] == {"avg": 70.0, "min": 60.0, "max": 80.0}
    assert result["series"]["columns"] == ["time", "avg", "min", "max"]
    assert result["series"]["rows"] == [
        ["2026-06-01T09:00:00+09:00", 70.0, 60.0, 80.0],
        ["2026-06-01T09:05:00+09:00", 70.0, 70.0, 70.0],
    ]
    assert repository.timeseries_calls[0][1].tzinfo is UTC


def test_timeseries_requires_metric_for_multi_metric_data_type():
    """複数metricの時系列を混ぜず、metric選択を要求する。"""
    # Arrange
    repository = FakeGoogleHealthQueryRepository()

    def get_hrv_timeseries(data_type, start_at, end_at, metric=None):
        return (
            [
                {
                    "measured_at_utc": datetime(2026, 6, 1),
                    "metric_name": metric or "rmssd",
                    "value": 48.0,
                    "unit": "millisecond",
                },
                {
                    "measured_at_utc": datetime(2026, 6, 1, 0, 1),
                    "metric_name": "sdnn",
                    "value": 52.0,
                    "unit": "millisecond",
                },
            ]
            if metric is None
            else [
                {
                    "measured_at_utc": datetime(2026, 6, 1),
                    "metric_name": metric,
                    "value": 48.0,
                    "unit": "millisecond",
                }
            ]
        )

    repository.get_timeseries = get_hrv_timeseries
    use_case = GetGoogleHealthTimeseriesUseCase(repository)

    # Act / Assert
    with pytest.raises(ValueError, match="available metrics|multiple metrics"):
        use_case.execute(
            "heart-rate-variability",
            "2026-06-01T00:00:00Z",
            "2026-06-01T01:00:00Z",
        )

    result = use_case.execute(
        "heart-rate-variability",
        "2026-06-01T00:00:00Z",
        "2026-06-01T01:00:00Z",
        metric="rmssd",
    )
    assert result["metric"] == "rmssd"
    assert result["stats"]["avg"] == 48.0


def test_timeseries_raw_limit_is_explicit():
    """rawが上限を超える場合は暗黙truncateせずエラーにする。"""
    # Arrange
    repository = FakeGoogleHealthQueryRepository()
    repository.get_timeseries = lambda *args: [
        {
            "measured_at_utc": datetime(2026, 6, 1),
            "metric_name": "heart_rate",
            "value": float(index),
            "unit": "bpm",
        }
        for index in range(1001)
    ]
    use_case = GetGoogleHealthTimeseriesUseCase(repository)

    # Act / Assert
    with pytest.raises(ValueError, match="raw result exceeds 1000 rows"):
        use_case.execute(
            "heart-rate",
            "2026-06-01T00:00:00Z",
            "2026-06-01T01:00:00Z",
            "raw",
        )


def test_timeseries_auto_uses_internal_bucket_for_long_ranges():
    """長期間のautoは1時間固定にせず80 bucket程度へ調整する。"""
    # Arrange
    use_case = GetGoogleHealthTimeseriesUseCase(FakeGoogleHealthQueryRepository())

    # Act
    result = use_case.execute(
        "heart-rate",
        "2026-06-01T00:00:00Z",
        "2026-06-08T00:00:00Z",
    )

    # Assert
    assert result["resolution"] == "126m"
    assert len(result["series"]["rows"]) <= 80


def test_sessions_and_record_keep_drill_down_linkage():
    """一覧のidをrecord detailへ渡せる形で返す。"""
    # Arrange
    repository = FakeGoogleHealthQueryRepository()
    sessions = GetGoogleHealthSessionsUseCase(
        repository,
        timezone=ZoneInfo("Asia/Tokyo"),
    )
    record = GetGoogleHealthRecordUseCase(repository)

    # Act
    session_result = sessions.execute("2026-06-01", "2026-06-01", "sleep")
    record_result = record.execute("rec-sleep")

    # Assert
    assert session_result["columns"] == [
        "id",
        "type",
        "start",
        "end",
        "duration_s",
        "session_type",
    ]
    assert session_result["rows"][0][0] == "rec-sleep"
    assert session_result["rows"][0][2] == "2026-06-01T08:00:00+09:00"
    assert record_result == {
        "id": "rec-sleep",
        "type": "sleep",
        "kind": "session",
        "date": "2026-06-01",
        "payload": {"type": "SLEEP", "unknown": True},
    }
