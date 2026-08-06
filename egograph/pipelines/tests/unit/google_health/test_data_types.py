"""Google Health data type registryのテスト。"""

from pipelines.sources.google_health.data_types import (
    DATA_TYPE_BY_NAME,
    FetchStrategy,
    RecordKind,
)


def test_registry_matches_fitbit_air_target_data_types():
    """計画で定義した28 data typeだけを取得対象にする。"""
    # Arrange
    expected = {
        "steps",
        "distance",
        "total-calories",
        "active-energy-burned",
        "active-minutes",
        "active-zone-minutes",
        "activity-level",
        "sedentary-period",
        "calories-in-heart-rate-zone",
        "time-in-heart-rate-zone",
        "exercise",
        "floors",
        "altitude",
        "swim-lengths-data",
        "daily-vo2-max",
        "vo2-max",
        "run-vo2-max",
        "heart-rate",
        "daily-resting-heart-rate",
        "heart-rate-variability",
        "daily-heart-rate-variability",
        "daily-heart-rate-zones",
        "oxygen-saturation",
        "daily-oxygen-saturation",
        "respiratory-rate-sleep-summary",
        "daily-respiratory-rate",
        "daily-sleep-temperature-derivations",
        "sleep",
    }

    # Act & Assert
    assert set(DATA_TYPE_BY_NAME) == expected
    assert DATA_TYPE_BY_NAME["steps"].record_kind is RecordKind.INTERVAL
    assert DATA_TYPE_BY_NAME["heart-rate"].record_kind is RecordKind.SAMPLE
    assert DATA_TYPE_BY_NAME["sleep"].record_kind is RecordKind.SESSION
    assert DATA_TYPE_BY_NAME["daily-oxygen-saturation"].record_kind is (
        RecordKind.DAILY
    )


def test_activity_level_uses_reconcile_only():
    """activity-levelは公式仕様でreconcileのみを利用する。"""
    # Arrange
    data_type = DATA_TYPE_BY_NAME["activity-level"]

    # Act & Assert
    assert data_type.fetch_strategy is FetchStrategy.RECONCILE
    assert not data_type.include_interval_rollup
