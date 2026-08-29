"""Google Health DataPoint の分析用 Projection。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipelines.sources.google_health.data_types import GoogleHealthDataType, RecordKind


@dataclass(frozen=True)
class MetricProjection:
    """1つの意味を持つ分析用 metric。"""

    metric_name: str
    value: float
    unit: str


def project_data_point(
    data_type: GoogleHealthDataType,
    payload: dict[str, Any],
    *,
    started_at: Any = None,
    ended_at: Any = None,
) -> list[MetricProjection]:
    """DataPoint の既知の値だけを分析用 metric へ変換する。

    完全な payload は ``records.payload_json`` が保持するため、ここでは
    Google Health の意味が確定している値だけを Projection する。未知の
    フィールドを数値だけで推測して保存することはしない。
    """
    if data_type.record_kind is RecordKind.SAMPLE:
        return _project_sample(data_type.name, payload)
    if data_type.record_kind is RecordKind.INTERVAL:
        return _project_interval(
            data_type.name,
            payload,
            started_at=started_at,
            ended_at=ended_at,
        )
    if data_type.record_kind is RecordKind.DAILY:
        return _project_daily(data_type.name, payload)
    return []


def project_rollup_data_point(
    data_type: GoogleHealthDataType,
    payload: dict[str, Any],
) -> list[MetricProjection]:
    """DailyRollup の専用payloadを分析用 metric へ変換する。

    DailyRollup は通常の DataPoint と同じ data type 名を使うが、payload の
    value 型は別の ``*RollupValue`` である。record kindだけで分岐すると
    interval/sample用のフィールドを誤って読むため、response kindを専用の
    Projection関数で扱う。
    """
    if data_type.name == "active-minutes":
        values = payload.get("activeMinutesRollupByActivityLevel")
        if not isinstance(values, list):
            return []
        projections = [
            _metric(f"active_minutes_{_snake_case(level)}", number, "minute")
            for item in values
            if isinstance(item, dict)
            if isinstance(level := item.get("activityLevel"), str)
            if (number := _number(item.get("activeMinutesSum"))) is not None
        ]
        if projections:
            projections.append(
                _metric(
                    "active_minutes",
                    sum(item.value for item in projections),
                    "minute",
                )
            )
        return projections

    if data_type.name == "active-zone-minutes":
        fields = (
            ("sumInFatBurnHeartZone", "active_zone_minutes_fat_burn"),
            ("sumInCardioHeartZone", "active_zone_minutes_cardio"),
            ("sumInPeakHeartZone", "active_zone_minutes_peak"),
        )
        projections = [
            _metric(metric_name, number, "minute")
            for field, metric_name in fields
            if (number := _number(payload.get(field))) is not None
        ]
        if projections:
            projections.append(
                _metric(
                    "active_zone_minutes",
                    sum(item.value for item in projections),
                    "minute",
                )
            )
        return projections

    if data_type.name == "calories-in-heart-rate-zone":
        values = payload.get("caloriesInHeartRateZones")
        if not isinstance(values, list):
            return []
        return [
            _metric(
                f"calories_in_heart_rate_zone_{_snake_case(zone)}",
                number,
                "kilocalorie",
            )
            for item in values
            if isinstance(item, dict)
            if isinstance(zone := item.get("heartRateZone"), str)
            if (number := _number(item.get("kcal"))) is not None
        ]

    if data_type.name == "time-in-heart-rate-zone":
        values = payload.get("timeInHeartRateZones")
        if not isinstance(values, list):
            return []
        return [
            _metric(
                f"time_in_heart_rate_zone_{_snake_case(zone)}",
                seconds,
                "second",
            )
            for item in values
            if isinstance(item, dict)
            if isinstance(zone := item.get("heartRateZone"), str)
            if (seconds := _duration_seconds(item.get("duration"))) is not None
        ]

    rollup_fields: dict[str, tuple[tuple[str, str, str], ...]] = {
        "steps": (("countSum", "steps", "count"),),
        "distance": (("millimetersSum", "distance", "millimeter"),),
        "active-energy-burned": (("kcalSum", "active_energy_burned", "kilocalorie"),),
        "floors": (("countSum", "floors", "count"),),
        "altitude": (("gainMillimetersSum", "altitude", "millimeter"),),
        "swim-lengths-data": (("strokeCountSum", "swim_lengths", "count"),),
        "sedentary-period": (("durationSum", "sedentary_period", "second"),),
        "total-calories": (("kcalSum", "total_calories", "kilocalorie"),),
        "heart-rate": (
            ("beatsPerMinuteAvg", "heart_rate_avg", "beats_per_minute"),
            ("beatsPerMinuteMin", "heart_rate_min", "beats_per_minute"),
            ("beatsPerMinuteMax", "heart_rate_max", "beats_per_minute"),
        ),
        "run-vo2-max": (
            ("rateAvg", "run_vo2_max_avg", "milliliter_per_kilogram_per_minute"),
            ("rateMin", "run_vo2_max_min", "milliliter_per_kilogram_per_minute"),
            ("rateMax", "run_vo2_max_max", "milliliter_per_kilogram_per_minute"),
        ),
    }
    fields = rollup_fields.get(data_type.name, ())
    result = []
    for field, metric_name, unit in fields:
        raw_value = payload.get(field)
        value = (
            _duration_seconds(raw_value)
            if data_type.name == "sedentary-period"
            else _number(raw_value)
        )
        if value is not None:
            result.append(_metric(metric_name, value, unit))
    return result


def _project_sample(
    data_type: str,
    payload: dict[str, Any],
) -> list[MetricProjection]:
    field_map: dict[str, tuple[tuple[str, ...], str, str]] = {
        "heart-rate": (("beatsPerMinute",), "heart_rate", "beats_per_minute"),
        "oxygen-saturation": (("percentage",), "oxygen_saturation", "percent"),
        "respiratory-rate": (
            ("breathsPerMinute",),
            "respiratory_rate",
            "breaths_per_minute",
        ),
        "skin-temperature": (
            ("temperatureCelsius",),
            "skin_temperature",
            "celsius",
        ),
        "vo2-max": (("vo2Max",), "vo2_max", "milliliter_per_kilogram_per_minute"),
        "run-vo2-max": (
            ("runVo2Max",),
            "run_vo2_max",
            "milliliter_per_kilogram_per_minute",
        ),
    }
    if data_type in field_map:
        path, metric_name, unit = field_map[data_type]
        value = _number(_at(payload, *path))
        if value is None:
            return []
        return [_metric(metric_name, value, unit)]

    if data_type == "heart-rate-variability":
        fields = (
            (
                "rootMeanSquareOfSuccessiveDifferencesMilliseconds",
                "rmssd",
            ),
            ("standardDeviationMilliseconds", "sdnn"),
        )
        return [
            _metric(metric_name, value, "millisecond")
            for field, metric_name in fields
            if (value := _number(payload.get(field))) is not None
        ]

    if data_type == "respiratory-rate-sleep-summary":
        return _project_respiratory_sleep_summary(payload)

    return []


def _project_respiratory_sleep_summary(
    payload: dict[str, Any],
) -> list[MetricProjection]:
    projections: list[MetricProjection] = []
    stats = (
        ("deepSleepStats", "deep_sleep"),
        ("lightSleepStats", "light_sleep"),
        ("remSleepStats", "rem_sleep"),
        ("fullSleepStats", "full_sleep"),
    )
    for field, prefix in stats:
        value = payload.get(field)
        if not isinstance(value, dict):
            continue
        for source, suffix, unit in (
            ("breathsPerMinute", "respiratory_rate", "breaths_per_minute"),
            ("standardDeviation", "standard_deviation", "breaths_per_minute"),
            ("signalToNoise", "signal_to_noise", "ratio"),
        ):
            number = _number(value.get(source))
            if number is not None:
                projections.append(_metric(f"{prefix}_{suffix}", number, unit))

    # 初期 API fixture / 旧データには fullSleepStats ではなく、payload直下に
    # breathsPerMinute がある形も存在する。これは仕様上同じ意味の値なので
    # canonical metric として扱う。
    if not projections:
        value = _number(payload.get("breathsPerMinute"))
        if value is not None:
            projections.append(_metric("respiratory_rate", value, "breaths_per_minute"))
    return projections


def _project_interval(
    data_type: str,
    payload: dict[str, Any],
    *,
    started_at: Any,
    ended_at: Any,
) -> list[MetricProjection]:
    field_map: dict[str, tuple[tuple[str, ...], str, str]] = {
        "steps": (("count",), "steps", "count"),
        "distance": (("millimeters",), "distance", "millimeter"),
        "active-energy-burned": (("kcal",), "active_energy_burned", "kilocalorie"),
        "active-zone-minutes": (
            ("activeZoneMinutes",),
            "active_zone_minutes",
            "minute",
        ),
        "floors": (("count",), "floors", "count"),
        "altitude": (("gainMillimeters",), "altitude", "millimeter"),
        "swim-lengths-data": (("strokeCount",), "swim_lengths", "count"),
        "calories-in-heart-rate-zone": (
            ("kilocaloriesSum",),
            "calories_in_heart_rate_zone",
            "kilocalorie",
        ),
    }
    if data_type in field_map:
        path, metric_name, unit = field_map[data_type]
        value = _number(_at(payload, *path))
        if value is None:
            value = _number(payload.get("countSum")) if data_type == "steps" else None
        if value is None and data_type == "distance":
            value = _number(payload.get("millimetersSum"))
        if value is None and data_type == "active-energy-burned":
            value = _number(payload.get("kilocaloriesSum"))
        if data_type in {"active-zone-minutes", "calories-in-heart-rate-zone"}:
            zone = payload.get("heartRateZone")
            if isinstance(zone, str):
                metric_name = f"{metric_name}_{_snake_case(zone)}"
        return [_metric(metric_name, value, unit)] if value is not None else []

    if data_type == "active-minutes":
        values = payload.get("activeMinutesByActivityLevel")
        if isinstance(values, list):
            result: list[MetricProjection] = []
            for item in values:
                if not isinstance(item, dict):
                    continue
                value = _number(item.get("activeMinutes"))
                level = item.get("activityLevel")
                if value is not None and isinstance(level, str):
                    result.append(
                        _metric(
                            f"active_minutes_{_snake_case(level)}",
                            value,
                            "minute",
                        )
                    )
            if result:
                return result
        value = _number(payload.get("activeMinutes"))
        return [_metric("active_minutes", value, "minute")] if value is not None else []

    if data_type == "activity-level":
        level = payload.get("activityLevelType") or payload.get("activityLevel")
        if isinstance(level, str):
            values = {
                "ACTIVITY_LEVEL_TYPE_UNSPECIFIED": 0.0,
                "SEDENTARY": 1.0,
                "LIGHT": 2.0,
                "LIGHTLY_ACTIVE": 2.0,
                "MODERATE": 3.0,
                "MODERATELY_ACTIVE": 3.0,
                "VIGOROUS": 4.0,
                "VERY_ACTIVE": 4.0,
            }
            number = values.get(level.upper())
            return [_metric("activity_level", number, "level")]
        return []

    if data_type in {"sedentary-period", "time-in-heart-rate-zone"}:
        if started_at is None or ended_at is None:
            return []
        seconds = (ended_at - started_at).total_seconds()
        metric_name = (
            "sedentary_period"
            if data_type == "sedentary-period"
            else "time_in_heart_rate_zone"
        )
        if data_type == "time-in-heart-rate-zone":
            zone = payload.get("heartRateZoneType")
            if isinstance(zone, str):
                metric_name = f"{metric_name}_{_snake_case(zone)}"
        return [_metric(metric_name, seconds, "second")]

    return []


def _project_daily(
    data_type: str,
    payload: dict[str, Any],
) -> list[MetricProjection]:
    fields: dict[str, tuple[tuple[str, ...], str, str]] = {
        "daily-resting-heart-rate": (
            ("beatsPerMinute",),
            "resting_heart_rate",
            "beats_per_minute",
        ),
        "daily-respiratory-rate": (
            ("breathsPerMinute",),
            "daily_respiratory_rate",
            "breaths_per_minute",
        ),
        "daily-sleep-temperature-derivations": (
            ("nightlyTemperatureCelsius",),
            "nightly_temperature",
            "celsius",
        ),
    }
    if data_type in fields:
        path, metric_name, unit = fields[data_type]
        value = _number(_at(payload, *path))
        result = [_metric(metric_name, value, unit)] if value is not None else []
        if data_type == "daily-sleep-temperature-derivations":
            for source, name in (
                ("baselineTemperatureCelsius", "baseline_temperature"),
                ("relativeNightlyStddev30dCelsius", "relative_nightly_stddev_30d"),
            ):
                number = _number(payload.get(source))
                if number is not None:
                    result.append(_metric(name, number, "celsius"))
        return result

    if data_type == "daily-heart-rate-variability":
        fields = (
            (
                "averageHeartRateVariabilityMilliseconds",
                "daily_hrv",
                "millisecond",
            ),
            ("nonRemHeartRateBeatsPerMinute", "non_rem_heart_rate", "beats_per_minute"),
            ("entropy", "entropy", "ratio"),
            (
                "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds",
                "deep_sleep_rmssd",
                "millisecond",
            ),
        )
        return [
            _metric(metric_name, value, unit)
            for field, metric_name, unit in fields
            if (value := _number(payload.get(field))) is not None
        ]

    if data_type == "daily-oxygen-saturation":
        fields = (
            ("averagePercentage", "daily_oxygen_saturation"),
            ("lowerBoundPercentage", "oxygen_saturation_lower_bound"),
            ("upperBoundPercentage", "oxygen_saturation_upper_bound"),
            ("standardDeviationPercentage", "oxygen_saturation_standard_deviation"),
        )
        return [
            _metric(metric_name, value, "percent")
            for field, metric_name in fields
            if (value := _number(payload.get(field))) is not None
        ]

    if data_type == "daily-heart-rate-zones":
        result: list[MetricProjection] = []
        zones = payload.get("heartRateZones")
        if not isinstance(zones, list):
            return result
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            zone_type = zone.get("heartRateZoneType")
            if not isinstance(zone_type, str):
                continue
            prefix = f"heart_rate_zone_{_snake_case(zone_type)}"
            for field, suffix in (
                ("minBeatsPerMinute", "min"),
                ("maxBeatsPerMinute", "max"),
            ):
                value = _number(zone.get(field))
                if value is not None:
                    result.append(
                        _metric(
                            f"{prefix}_{suffix}",
                            value,
                            "beats_per_minute",
                        )
                    )
        return result

    daily_fields: dict[str, tuple[tuple[str, ...], str, str, tuple[str, ...]]] = {
        "steps": (("countSum",), "steps", "count", ("count",)),
        "distance": (("millimetersSum",), "distance", "millimeter", ("millimeters",)),
        "active-energy-burned": (
            ("kilocaloriesSum",),
            "active_energy_burned",
            "kilocalorie",
            ("kcal",),
        ),
        "active-minutes": (
            ("activeMinutesSum",),
            "active_minutes",
            "minute",
            ("activeMinutes",),
        ),
        "active-zone-minutes": (
            ("activeZoneMinutesSum",),
            "active_zone_minutes",
            "minute",
            ("activeZoneMinutes",),
        ),
        "sedentary-period": (("durationSecondsSum",), "sedentary_period", "second", ()),
        "time-in-heart-rate-zone": (
            ("durationSecondsSum",),
            "time_in_heart_rate_zone",
            "second",
            (),
        ),
        "floors": (("countSum",), "floors", "count", ("count",)),
        "altitude": (
            ("millimetersSum",),
            "altitude",
            "millimeter",
            ("gainMillimeters",),
        ),
        "swim-lengths-data": (("countSum",), "swim_lengths", "count", ("strokeCount",)),
        "calories-in-heart-rate-zone": (
            ("kilocaloriesSum",),
            "calories_in_heart_rate_zone",
            "kilocalorie",
            (),
        ),
        "total-calories": (
            ("kilocaloriesSum",),
            "total_calories",
            "kilocalorie",
            ("kcal",),
        ),
    }
    if data_type in daily_fields:
        path, metric_name, unit, fallbacks = daily_fields[data_type]
        value = _number(_at(payload, *path))
        if value is None:
            for fallback in fallbacks:
                value = _number(payload.get(fallback))
                if value is not None:
                    break
        return [_metric(metric_name, value, unit)] if value is not None else []

    if data_type in {"daily-vo2-max"}:
        value = _number(payload.get("vo2Max"))
        return (
            [_metric("daily_vo2_max", value, "milliliter_per_kilogram_per_minute")]
            if value is not None
            else []
        )

    return []


def _metric(metric_name: str, value: float | None, unit: str) -> MetricProjection:
    if value is None:
        raise ValueError("metric_value_required")
    return MetricProjection(metric_name=metric_name, value=value, unit=unit)


def _at(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value[:-1]) if value.endswith("s") else float(value)
        except ValueError:
            return None
    return None


def _duration_seconds(value: Any) -> float | None:
    """Google protobuf Durationを秒の数値へ変換する。"""
    if isinstance(value, dict):
        seconds = _number(value.get("seconds"))
        nanos = _number(value.get("nanos")) or 0.0
        return seconds + nanos / 1_000_000_000 if seconds is not None else None
    return _number(value)


def _snake_case(value: str) -> str:
    if value.isupper():
        return value.lower()
    result = []
    for char in value:
        if char.isupper():
            result.append("_")
        result.append(char.lower())
    return "".join(result).lstrip("_")
