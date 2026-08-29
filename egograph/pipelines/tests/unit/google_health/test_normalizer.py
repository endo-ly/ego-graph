"""Google Health normalizerのテスト。"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
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


def test_hrv_data_point_creates_one_record_and_two_projection_metrics():
    """複数の既知数値を持つDataPointを欠落なく保存する。"""
    # Arrange
    payload = {
        "reconcileResponses": [
            {
                "dataPoints": [
                    {
                        "dataPointName": "hrv-1",
                        "heartRateVariability": {
                            "sampleTime": {"physicalTime": "2026-06-01T01:02:03Z"},
                            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 48.3,
                            "standardDeviationMilliseconds": 52.1,
                            "unknownField": {"preserved": True},
                        },
                    }
                ]
            }
        ]
    }

    # Act
    result = normalize_google_health_payload(
        connection_id="connection-1",
        data_type=DATA_TYPE_BY_NAME["heart-rate-variability"],
        payload=payload,
        raw_ref="raw/google_health/hrv.json",
    )

    # Assert
    assert len(result["records"]) == 1
    assert {row["metric_name"] for row in result["samples"]} == {"rmssd", "sdnn"}
    assert '"unknownField":{"preserved":true}' in result["records"][0]["payload_json"]
    assert result["samples"][0]["record_id"] == result["samples"][1]["record_id"]


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


def test_interval_projection_keeps_multiple_activity_level_metrics():
    """1つのintervalに含まれる活動レベル別metricをすべて保存する。"""
    # Arrange & Act
    result = _normalize(
        "active-minutes",
        {
            "activeMinutes": {
                "interval": {
                    "startTime": "2026-06-01T00:00:00Z",
                    "endTime": "2026-06-01T01:00:00Z",
                },
                "activeMinutesByActivityLevel": [
                    {"activityLevel": "LIGHT", "activeMinutes": "12"},
                    {"activityLevel": "MODERATE", "activeMinutes": "8"},
                ],
            }
        },
    )

    # Assert
    assert len(result["records"]) == 1
    assert {(row["metric_name"], row["value"]) for row in result["intervals"]} == {
        ("active_minutes_light", 12.0),
        ("active_minutes_moderate", 8.0),
    }
    assert {row["record_id"] for row in result["intervals"]} == {
        result["records"][0]["record_id"]
    }


@pytest.mark.parametrize(
    "data_type,payload,expected_metrics",
    [
        ("steps", {"countSum": 1000}, {("steps", 1000.0)}),
        ("distance", {"millimetersSum": 2500}, {("distance", 2500.0)}),
        (
            "active-energy-burned",
            {"kcalSum": 42.5},
            {("active_energy_burned", 42.5)},
        ),
        (
            "active-minutes",
            {
                "activeMinutesRollupByActivityLevel": [
                    {"activityLevel": "LIGHT", "activeMinutesSum": 12},
                    {"activityLevel": "VIGOROUS", "activeMinutesSum": 8},
                ]
            },
            {
                ("active_minutes_light", 12.0),
                ("active_minutes_vigorous", 8.0),
                ("active_minutes", 20.0),
            },
        ),
        (
            "active-zone-minutes",
            {
                "sumInFatBurnHeartZone": 10,
                "sumInCardioHeartZone": 20,
                "sumInPeakHeartZone": 5,
            },
            {
                ("active_zone_minutes_fat_burn", 10.0),
                ("active_zone_minutes_cardio", 20.0),
                ("active_zone_minutes_peak", 5.0),
                ("active_zone_minutes", 35.0),
            },
        ),
        (
            "sedentary-period",
            {"durationSum": "90s"},
            {("sedentary_period", 90.0)},
        ),
        (
            "time-in-heart-rate-zone",
            {
                "timeInHeartRateZones": [
                    {"heartRateZone": "LIGHT", "duration": "60s"},
                    {"heartRateZone": "CARDIO", "duration": "120s"},
                ]
            },
            {
                ("time_in_heart_rate_zone_light", 60.0),
                ("time_in_heart_rate_zone_cardio", 120.0),
            },
        ),
        ("floors", {"countSum": 3}, {("floors", 3.0)}),
        ("altitude", {"gainMillimetersSum": 400}, {("altitude", 400.0)}),
        (
            "swim-lengths-data",
            {"strokeCountSum": 50},
            {("swim_lengths", 50.0)},
        ),
        (
            "run-vo2-max",
            {"rateAvg": 42.0, "rateMin": 40.0, "rateMax": 44.0},
            {
                ("run_vo2_max_avg", 42.0),
                ("run_vo2_max_min", 40.0),
                ("run_vo2_max_max", 44.0),
            },
        ),
        (
            "heart-rate",
            {
                "beatsPerMinuteAvg": 72.0,
                "beatsPerMinuteMin": 60.0,
                "beatsPerMinuteMax": 90.0,
            },
            {
                ("heart_rate_avg", 72.0),
                ("heart_rate_min", 60.0),
                ("heart_rate_max", 90.0),
            },
        ),
        (
            "calories-in-heart-rate-zone",
            {
                "caloriesInHeartRateZones": [
                    {"heartRateZone": "CARDIO", "kcal": 30.0},
                    {"heartRateZone": "PEAK", "kcal": 10.0},
                ]
            },
            {
                ("calories_in_heart_rate_zone_cardio", 30.0),
                ("calories_in_heart_rate_zone_peak", 10.0),
            },
        ),
        (
            "total-calories",
            {"kcalSum": 1800.0},
            {("total_calories", 1800.0)},
        ),
    ],
)
def test_daily_rollup_uses_rollup_value_projection(
    data_type,
    payload,
    expected_metrics,
):
    """全DailyRollup対応data typeを専用RollupValueとして射影する。"""
    # Arrange
    data_type_definition = DATA_TYPE_BY_NAME[data_type]
    point = {
        "civilStartTime": {"date": {"year": 2026, "month": 6, "day": 1}},
        data_type_definition.payload_name: payload,
    }

    # Act
    result = normalize_google_health_payload(
        connection_id="connection-1",
        data_type=data_type_definition,
        payload={"dailyRollupResponses": [{"rollupDataPoints": [point]}]},
        raw_ref="raw/google_health/rollup.json",
    )

    # Assert
    assert len(result["records"]) == 1
    assert {
        (row["metric_name"], row["value"]) for row in result["daily_metrics"]
    } == expected_metrics


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
