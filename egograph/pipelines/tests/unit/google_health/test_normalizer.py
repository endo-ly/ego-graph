"""Google Health normalizerのテスト。"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pipelines.sources.google_health.data_types import DATA_TYPE_BY_NAME
from pipelines.sources.google_health.normalizer import (
    aggregate_daily_metrics,
    normalize_google_health_payload,
)


def _normalize(data_type, point, *, rollup=False):
    return normalize_google_health_payload(
        connection_id="connection-1",
        data_type=DATA_TYPE_BY_NAME[data_type],
        payload={
            "reconcileResponses": [] if rollup else [{"dataPoints": [point]}],
            "dailyRollupResponses": ([{"rollupDataPoints": [point]}] if rollup else []),
        },
        raw_ref="raw/google_health/example.json",
        ingested_at=datetime(2026, 6, 4, tzinfo=UTC),
    )


def test_normalizes_sample_interval_session_and_daily_records():
    """4種類のParquet schemaへ必要な列を変換する。"""
    # Arrange & Act
    sample = _normalize(
        "heart-rate",
        {
            "heartRate": {
                "sampleTime": {"physicalTime": "2026-06-01T01:00:00Z"},
                "beatsPerMinute": 72,
            },
            "dataSource": {"device": {"displayName": "Fitbit Air"}},
        },
    )
    interval = _normalize(
        "steps",
        {
            "steps": {
                "interval": {
                    "startTime": "2026-06-01T00:00:00Z",
                    "endTime": "2026-06-01T00:05:00Z",
                },
                "count": 120,
            }
        },
    )
    session = _normalize(
        "sleep",
        {
            "dataPointName": "sleep-1",
            "sleep": {
                "interval": {
                    "startTime": "2026-05-31T23:00:00Z",
                    "endTime": "2026-06-01T07:00:00Z",
                },
                "type": "SLEEP",
            },
        },
    )
    daily = _normalize(
        "steps",
        {
            "civilStartTime": {"date": {"year": 2026, "month": 6, "day": 1}},
            "steps": {"countSum": "1000"},
        },
        rollup=True,
    )

    # Assert
    assert sample["samples"][0]["value"] == 72
    assert sample["samples"][0]["device_family"] == "fitbit_air"
    assert interval["intervals"][0]["value"] == 120
    assert session["sessions"][0]["duration_seconds"] == 8 * 60 * 60
    assert session["daily_metrics"][0]["metric_name"] == "sleep_duration"
    assert daily["daily_metrics"][0]["value"] == 1000
    assert daily["daily_metrics"][0]["raw_ref"].startswith("raw/")


def test_aggregate_daily_metrics_sums_multiple_sessions():
    """同日の複数sessionから作った日次値を1行へ集約する。"""
    # Arrange
    first = _normalize(
        "exercise",
        {
            "exercise": {
                "interval": {
                    "startTime": "2026-06-01T01:00:00Z",
                    "endTime": "2026-06-01T01:30:00Z",
                }
            }
        },
    )["daily_metrics"][0]
    second = {**first, "value": 900.0}

    # Act
    result = aggregate_daily_metrics([first, second])

    # Assert
    assert len(result) == 1
    assert result[0]["value"] == 2700


def test_derived_daily_date_uses_configured_timezone_and_keeps_utc_timestamp():
    """派生日次は設定TZの日付、時刻列はUTCで保存する。"""
    # Arrange
    point = {
        "dataPointName": "sleep-1",
        "sleep": {
            "interval": {
                "startTime": "2026-05-31T15:30:00Z",
                "endTime": "2026-05-31T23:00:00Z",
            },
            "type": "SLEEP",
        },
    }

    # Act
    result = normalize_google_health_payload(
        connection_id="connection-1",
        data_type=DATA_TYPE_BY_NAME["sleep"],
        payload={"reconcileResponses": [{"dataPoints": [point]}]},
        raw_ref="raw/example.json",
        timezone=ZoneInfo("Asia/Tokyo"),
    )

    # Assert
    assert result["daily_metrics"][0]["date"].isoformat() == "2026-06-01"
    assert result["sessions"][0]["ended_at_utc"] == datetime(
        2026,
        5,
        31,
        23,
        tzinfo=UTC,
    )


def test_normalizes_physical_rollup_and_averages_respiratory_daily():
    """physical rollupをintervalへ、呼吸数sampleを日次平均へ変換する。"""
    # Arrange
    interval = normalize_google_health_payload(
        connection_id="connection-1",
        data_type=DATA_TYPE_BY_NAME["calories-in-heart-rate-zone"],
        payload={
            "reconcileResponses": [],
            "rollupResponses": [
                {
                    "rollupDataPoints": [
                        {
                            "startTime": "2026-06-01T00:00:00Z",
                            "endTime": "2026-06-01T00:05:00Z",
                            "caloriesInHeartRateZone": {"kilocaloriesSum": "2.5"},
                        }
                    ]
                }
            ],
            "dailyRollupResponses": [],
        },
        raw_ref="raw/example.json",
    )
    respiratory = [
        {
            **_normalize(
                "respiratory-rate-sleep-summary",
                {
                    "respiratoryRateSleepSummary": {
                        "sampleTime": {"physicalTime": f"2026-06-01T0{hour}:00:00Z"},
                        "breathsPerMinute": value,
                    }
                },
            )["daily_metrics"][0]
        }
        for hour, value in ((1, 12), (2, 16))
    ]

    # Act
    daily = aggregate_daily_metrics(respiratory)

    # Assert
    assert interval["intervals"][0]["value"] == 2.5
    assert daily[0]["value"] == 14


def test_normalizes_categorical_and_duration_only_intervals():
    """数値を持たないintervalをlevelまたは継続秒へ変換する。"""
    # Arrange & Act
    activity_level = _normalize(
        "activity-level",
        {
            "activityLevel": {
                "interval": {
                    "startTime": "2026-06-01T00:00:00Z",
                    "endTime": "2026-06-01T00:05:00Z",
                },
                "activityLevelType": "MODERATE",
            }
        },
    )
    sedentary = _normalize(
        "sedentary-period",
        {
            "sedentaryPeriod": {
                "interval": {
                    "startTime": "2026-06-01T00:00:00Z",
                    "endTime": "2026-06-01T00:10:00Z",
                }
            }
        },
    )

    # Assert
    assert activity_level["intervals"][0]["value"] == 3
    assert sedentary["intervals"][0]["value"] == 600


def test_skips_records_with_invalid_date_or_datetime():
    """不正なAPI日時を含む行だけをスキップする。"""
    invalid_sample = _normalize(
        "heart-rate",
        {
            "heartRate": {
                "sampleTime": {"physicalTime": "invalid"},
                "beatsPerMinute": 72,
            }
        },
    )
    invalid_daily = _normalize(
        "steps",
        {
            "civilStartTime": "invalid",
            "steps": {"countSum": "1000"},
        },
        rollup=True,
    )

    assert invalid_sample["samples"] == []
    assert invalid_daily["daily_metrics"] == []
