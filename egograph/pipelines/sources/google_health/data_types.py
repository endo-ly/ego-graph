"""Fitbit Air から取得する Google Health data type registry."""

from dataclasses import dataclass
from enum import StrEnum


class DataCategory(StrEnum):
    """Google Health data category。"""

    ACTIVITY = "activity"
    HEALTH_METRICS = "health_metrics"
    SLEEP = "sleep"


@dataclass(frozen=True)
class GoogleHealthDataType:
    """取得対象 data type の定義。"""

    name: str
    category: DataCategory
    supports_list: bool = True
    smoke_test: bool = False


DATA_TYPES = (
    GoogleHealthDataType("steps", DataCategory.ACTIVITY, smoke_test=True),
    GoogleHealthDataType("distance", DataCategory.ACTIVITY),
    GoogleHealthDataType("total-calories", DataCategory.ACTIVITY),
    GoogleHealthDataType("active-energy-burned", DataCategory.ACTIVITY),
    GoogleHealthDataType("active-minutes", DataCategory.ACTIVITY),
    GoogleHealthDataType("active-zone-minutes", DataCategory.ACTIVITY),
    GoogleHealthDataType("activity-level", DataCategory.ACTIVITY),
    GoogleHealthDataType("sedentary-period", DataCategory.ACTIVITY),
    GoogleHealthDataType("calories-in-heart-rate-zone", DataCategory.ACTIVITY),
    GoogleHealthDataType("time-in-heart-rate-zone", DataCategory.ACTIVITY),
    GoogleHealthDataType("exercise", DataCategory.ACTIVITY),
    GoogleHealthDataType("floors", DataCategory.ACTIVITY),
    GoogleHealthDataType("altitude", DataCategory.ACTIVITY),
    GoogleHealthDataType("swim-lengths-data", DataCategory.ACTIVITY),
    GoogleHealthDataType("daily-vo2-max", DataCategory.ACTIVITY),
    GoogleHealthDataType("vo2-max", DataCategory.ACTIVITY),
    GoogleHealthDataType("run-vo2-max", DataCategory.ACTIVITY),
    GoogleHealthDataType("heart-rate", DataCategory.HEALTH_METRICS),
    GoogleHealthDataType("daily-resting-heart-rate", DataCategory.HEALTH_METRICS),
    GoogleHealthDataType("heart-rate-variability", DataCategory.HEALTH_METRICS),
    GoogleHealthDataType(
        "daily-heart-rate-variability",
        DataCategory.HEALTH_METRICS,
    ),
    GoogleHealthDataType("daily-heart-rate-zones", DataCategory.HEALTH_METRICS),
    GoogleHealthDataType("oxygen-saturation", DataCategory.HEALTH_METRICS),
    GoogleHealthDataType(
        "daily-oxygen-saturation",
        DataCategory.HEALTH_METRICS,
    ),
    GoogleHealthDataType(
        "respiratory-rate-sleep-summary",
        DataCategory.HEALTH_METRICS,
    ),
    GoogleHealthDataType("daily-respiratory-rate", DataCategory.HEALTH_METRICS),
    GoogleHealthDataType(
        "daily-sleep-temperature-derivations",
        DataCategory.HEALTH_METRICS,
    ),
    GoogleHealthDataType("sleep", DataCategory.SLEEP, smoke_test=True),
)

SMOKE_TEST_DATA_TYPES = tuple(item.name for item in DATA_TYPES if item.smoke_test)
