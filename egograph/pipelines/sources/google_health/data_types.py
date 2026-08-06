"""Fitbit Air から取得する Google Health data type registry。"""

from dataclasses import dataclass
from enum import StrEnum


class DataCategory(StrEnum):
    """Google Health data category。"""

    ACTIVITY = "activity"
    HEALTH_METRICS = "health_metrics"
    SLEEP = "sleep"


class RecordKind(StrEnum):
    """正規化後のrecord種別。"""

    DAILY = "daily"
    SAMPLE = "sample"
    INTERVAL = "interval"
    SESSION = "session"


class FetchStrategy(StrEnum):
    """data point取得方式。"""

    RECONCILE = "reconcile"
    ROLLUP = "rollup"
    DAILY_ROLLUP = "daily_rollup"


@dataclass(frozen=True)
class GoogleHealthDataType:
    """取得対象data typeの定義。"""

    name: str
    category: DataCategory
    record_kind: RecordKind
    unit: str
    fetch_strategy: FetchStrategy = FetchStrategy.RECONCILE
    include_interval_rollup: bool = False
    include_daily_rollup: bool = False
    smoke_test: bool = False

    @property
    def filter_name(self) -> str:
        """filter式で使用するsnake_case名を返す。"""
        return self.name.replace("-", "_")

    @property
    def payload_name(self) -> str:
        """API payloadで使用するlowerCamelCase名を返す。"""
        parts = self.name.split("-")
        return parts[0] + "".join(part.title() for part in parts[1:])


DATA_TYPES = (
    GoogleHealthDataType(
        "steps",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "count",
        include_daily_rollup=True,
        smoke_test=True,
    ),
    GoogleHealthDataType(
        "distance",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "millimeter",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "total-calories",
        DataCategory.ACTIVITY,
        RecordKind.DAILY,
        "kilocalorie",
        fetch_strategy=FetchStrategy.DAILY_ROLLUP,
    ),
    GoogleHealthDataType(
        "active-energy-burned",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "kilocalorie",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "active-minutes",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "minute",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "active-zone-minutes",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "minute",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "activity-level",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "second",
    ),
    GoogleHealthDataType(
        "sedentary-period",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "second",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "calories-in-heart-rate-zone",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "kilocalorie",
        fetch_strategy=FetchStrategy.DAILY_ROLLUP,
        include_interval_rollup=True,
    ),
    GoogleHealthDataType(
        "time-in-heart-rate-zone",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "second",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "exercise",
        DataCategory.ACTIVITY,
        RecordKind.SESSION,
        "second",
    ),
    GoogleHealthDataType(
        "floors",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "count",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "altitude",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "millimeter",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "swim-lengths-data",
        DataCategory.ACTIVITY,
        RecordKind.INTERVAL,
        "count",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "daily-vo2-max",
        DataCategory.ACTIVITY,
        RecordKind.DAILY,
        "milliliter_per_kilogram_per_minute",
    ),
    GoogleHealthDataType(
        "vo2-max",
        DataCategory.ACTIVITY,
        RecordKind.SAMPLE,
        "milliliter_per_kilogram_per_minute",
    ),
    GoogleHealthDataType(
        "run-vo2-max",
        DataCategory.ACTIVITY,
        RecordKind.SAMPLE,
        "milliliter_per_kilogram_per_minute",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "heart-rate",
        DataCategory.HEALTH_METRICS,
        RecordKind.SAMPLE,
        "beats_per_minute",
        include_daily_rollup=True,
    ),
    GoogleHealthDataType(
        "daily-resting-heart-rate",
        DataCategory.HEALTH_METRICS,
        RecordKind.DAILY,
        "beats_per_minute",
    ),
    GoogleHealthDataType(
        "heart-rate-variability",
        DataCategory.HEALTH_METRICS,
        RecordKind.SAMPLE,
        "millisecond",
    ),
    GoogleHealthDataType(
        "daily-heart-rate-variability",
        DataCategory.HEALTH_METRICS,
        RecordKind.DAILY,
        "millisecond",
    ),
    GoogleHealthDataType(
        "daily-heart-rate-zones",
        DataCategory.HEALTH_METRICS,
        RecordKind.DAILY,
        "beats_per_minute",
    ),
    GoogleHealthDataType(
        "oxygen-saturation",
        DataCategory.HEALTH_METRICS,
        RecordKind.SAMPLE,
        "percent",
    ),
    GoogleHealthDataType(
        "daily-oxygen-saturation",
        DataCategory.HEALTH_METRICS,
        RecordKind.DAILY,
        "percent",
    ),
    GoogleHealthDataType(
        "respiratory-rate-sleep-summary",
        DataCategory.HEALTH_METRICS,
        RecordKind.SAMPLE,
        "breaths_per_minute",
    ),
    GoogleHealthDataType(
        "daily-respiratory-rate",
        DataCategory.HEALTH_METRICS,
        RecordKind.DAILY,
        "breaths_per_minute",
    ),
    GoogleHealthDataType(
        "daily-sleep-temperature-derivations",
        DataCategory.HEALTH_METRICS,
        RecordKind.DAILY,
        "celsius",
    ),
    GoogleHealthDataType(
        "sleep",
        DataCategory.SLEEP,
        RecordKind.SESSION,
        "second",
        smoke_test=True,
    ),
)

DATA_TYPE_BY_NAME = {item.name: item for item in DATA_TYPES}
SMOKE_TEST_DATA_TYPES = tuple(item.name for item in DATA_TYPES if item.smoke_test)
