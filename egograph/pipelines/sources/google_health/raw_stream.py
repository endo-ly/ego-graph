"""Google Health Raw JSONをDataPoint単位でstreaming読み込みする。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

import ijson
from ijson.common import JSONError

_POINT_PATHS = {
    "reconcileResponses.item.dataPoints.item": (
        "reconcileResponses",
        "dataPoints",
    ),
    "rollupResponses.item.rollupDataPoints.item": (
        "rollupResponses",
        "rollupDataPoints",
    ),
    "dailyRollupResponses.item.rollupDataPoints.item": (
        "dailyRollupResponses",
        "rollupDataPoints",
    ),
}
_RESPONSE_ITEM_PATHS = frozenset(
    {
        "reconcileResponses.item",
        "rollupResponses.item",
        "dailyRollupResponses.item",
    }
)
_POINT_ARRAY_PATHS = frozenset(
    {
        "reconcileResponses.item.dataPoints",
        "rollupResponses.item.rollupDataPoints",
        "dailyRollupResponses.item.rollupDataPoints",
    }
)
_ARRAY_FIELDS = frozenset(
    {
        "reconcileResponses",
        "rollupResponses",
        "dailyRollupResponses",
    }
)


@dataclass(frozen=True)
class RawPointChunk:
    """同じresponse種別のDataPoint chunk。"""

    response_field: str
    point_field: str
    points: list[dict[str, Any]]

    def as_payload(self) -> dict[str, Any]:
        """既存Normalizerが受け取れる最小payloadへ変換する。"""
        return {
            self.response_field: [{self.point_field: self.points}],
        }


def iter_raw_point_chunks(
    body: BinaryIO,
    *,
    chunk_size: int,
) -> Iterator[RawPointChunk]:
    """Raw JSONを最大``chunk_size``件ずつDataPointへ分割する。

    ``body``はseekせず1回だけ読み進める。配列以外のRawトップレベル要素は
    JSONの構文として正しくても、Google Health Rawの配列契約に反するため
    エラーとして扱う。
    """
    if chunk_size <= 0:
        raise ValueError("invalid_chunk_size: must be positive")

    events = ijson.parse(body, use_float=True)
    root_started = False
    root_ended = False
    current_spec: tuple[str, str] | None = None
    current_points: list[dict[str, Any]] = []

    try:
        for prefix, event, value in events:
            if not root_started:
                if prefix != "" or event != "start_map":
                    raise ValueError(
                        "invalid_raw_google_health_payload: root object required"
                    )
                root_started = True
                continue

            if prefix == "" and event == "end_map":
                root_ended = True
                continue

            if prefix == "" and event == "map_key" and value in _ARRAY_FIELDS:
                continue

            if prefix in _ARRAY_FIELDS | _POINT_ARRAY_PATHS and event not in {
                "start_array",
                "end_array",
            }:
                raise ValueError(
                    f"invalid_raw_google_health_payload: {prefix} must be an array"
                )

            if prefix in _RESPONSE_ITEM_PATHS and event not in {
                "start_map",
                "end_map",
                "map_key",
            }:
                raise ValueError(
                    "invalid_raw_google_health_payload: response must be an object"
                )

            spec = _POINT_PATHS.get(prefix)
            if spec is None:
                continue
            if event != "start_map":
                raise ValueError(
                    "invalid_raw_google_health_payload: DataPoint must be an object"
                )

            point = _read_value(events, event)
            if not isinstance(point, dict):
                raise ValueError(
                    "invalid_raw_google_health_payload: DataPoint must be an object"
                )
            if current_spec != spec:
                if current_points:
                    yield RawPointChunk(
                        response_field=current_spec[0],
                        point_field=current_spec[1],
                        points=current_points,
                    )
                current_spec = spec
                current_points = []
            current_points.append(point)
            if len(current_points) == chunk_size:
                yield RawPointChunk(
                    response_field=spec[0],
                    point_field=spec[1],
                    points=current_points,
                )
                current_points = []
        if not root_started or not root_ended:
            raise ValueError(
                "invalid_raw_google_health_payload: incomplete root object"
            )
    except (JSONError, StopIteration, TypeError) as exc:
        raise ValueError("invalid_raw_google_health_json") from exc

    if current_points and current_spec is not None:
        yield RawPointChunk(
            response_field=current_spec[0],
            point_field=current_spec[1],
            points=current_points,
        )


def _read_value(
    events: Iterator[tuple[str, str, Any]],
    event: str,
    value: Any = None,
) -> Any:
    """現在のJSON valueをevent iteratorから再帰的に読み取る。"""
    if event == "start_map":
        result: dict[str, Any] = {}
        while True:
            _prefix, nested_event, value = next(events)
            if nested_event == "end_map":
                return result
            if nested_event != "map_key":
                raise ValueError("invalid_raw_google_health_json")
            _prefix, value_event, value_value = next(events)
            result[value] = _read_value(events, value_event, value_value)

    if event == "start_array":
        result: list[Any] = []
        while True:
            _prefix, nested_event, value = next(events)
            if nested_event == "end_array":
                return result
            result.append(_read_value(events, nested_event, value))

    return value
