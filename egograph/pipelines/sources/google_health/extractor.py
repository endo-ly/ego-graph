"""Google Health data type単位の取得処理。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pipelines.sources.google_health.client import GoogleHealthAPIClient
from pipelines.sources.google_health.data_types import (
    FetchStrategy,
    GoogleHealthDataType,
    RecordKind,
)
from pipelines.sources.google_health.timezone import local_date_start_rfc3339

DEFAULT_PAGE_SIZE = 10_000
SESSION_PAGE_SIZE = 25
INTERVAL_ROLLUP_WINDOW_SECONDS = 300
SHORT_ROLLUP_DATA_TYPES = {
    "active-minutes",
    "calories-in-heart-rate-zone",
    "heart-rate",
    "total-calories",
}


@dataclass(frozen=True)
class ExtractedGoogleHealthData:
    """1 data type分のAPIレスポンス原本。"""

    payload: dict[str, Any]
    record_count: int


class GoogleHealthExtractor:
    """期間指定、pagination、daily rollup分割を扱う。"""

    def __init__(
        self,
        client: GoogleHealthAPIClient,
        *,
        timezone: ZoneInfo | None = None,
    ) -> None:
        self._client = client
        self._timezone = timezone or ZoneInfo("UTC")

    def extract(
        self,
        *,
        connection_id: str,
        data_type: GoogleHealthDataType,
        date_from: date,
        date_to: date,
    ) -> ExtractedGoogleHealthData:
        """指定data typeの期間内データをすべて取得する。"""
        if date_from >= date_to:
            raise ValueError("date_from must be earlier than date_to")
        reconcile_responses: list[dict[str, Any]] = []
        rollup_responses: list[dict[str, Any]] = []
        daily_rollup_responses: list[dict[str, Any]] = []

        if data_type.fetch_strategy is FetchStrategy.RECONCILE:
            reconcile_responses = self._fetch_reconciled_pages(
                connection_id=connection_id,
                data_type=data_type,
                date_from=date_from,
                date_to=date_to,
            )
        if data_type.include_interval_rollup:
            rollup_responses = self._fetch_interval_rollups(
                connection_id=connection_id,
                data_type=data_type,
                date_from=date_from,
                date_to=date_to,
            )
        if (
            data_type.fetch_strategy is FetchStrategy.DAILY_ROLLUP
            or data_type.include_daily_rollup
        ):
            daily_rollup_responses = self._fetch_daily_rollups(
                connection_id=connection_id,
                data_type=data_type,
                date_from=date_from,
                date_to=date_to,
            )

        record_count = (
            sum(len(response.get("dataPoints", [])) for response in reconcile_responses)
            + sum(
                len(response.get("rollupDataPoints", []))
                for response in rollup_responses
            )
            + sum(
                len(response.get("rollupDataPoints", []))
                for response in daily_rollup_responses
            )
        )
        return ExtractedGoogleHealthData(
            payload={
                "dataType": data_type.name,
                "range": {
                    "from": date_from.isoformat(),
                    "to": date_to.isoformat(),
                },
                "reconcileResponses": reconcile_responses,
                "rollupResponses": rollup_responses,
                "dailyRollupResponses": daily_rollup_responses,
            },
            record_count=record_count,
        )

    def _fetch_reconciled_pages(
        self,
        *,
        connection_id: str,
        data_type: GoogleHealthDataType,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            response = self._client.reconcile_data_points(
                connection_id,
                data_type.name,
                filter_expression=_build_filter(
                    data_type,
                    date_from,
                    date_to,
                    timezone=self._timezone,
                ),
                page_size=(
                    SESSION_PAGE_SIZE
                    if data_type.record_kind is RecordKind.SESSION
                    else DEFAULT_PAGE_SIZE
                ),
                page_token=page_token,
            )
            responses.append(response)
            next_page_token = response.get("nextPageToken")
            if not isinstance(next_page_token, str) or not next_page_token:
                return responses
            if next_page_token in seen_page_tokens:
                raise RuntimeError("google_health_repeated_page_token")
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

    def _fetch_daily_rollups(
        self,
        *,
        connection_id: str,
        data_type: GoogleHealthDataType,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        max_days = 14 if data_type.name in SHORT_ROLLUP_DATA_TYPES else 90
        chunk_start = date_from
        while chunk_start < date_to:
            chunk_end = min(chunk_start + timedelta(days=max_days), date_to)
            page_token: str | None = None
            seen_page_tokens: set[str] = set()
            while True:
                response = self._client.daily_rollup(
                    connection_id,
                    data_type.name,
                    date_from=chunk_start,
                    date_to=chunk_end,
                    page_token=page_token,
                )
                responses.append(response)
                next_page_token = response.get("nextPageToken")
                if not isinstance(next_page_token, str) or not next_page_token:
                    break
                if next_page_token in seen_page_tokens:
                    raise RuntimeError("google_health_repeated_page_token")
                seen_page_tokens.add(next_page_token)
                page_token = next_page_token
            chunk_start = chunk_end
        return responses

    def _fetch_interval_rollups(
        self,
        *,
        connection_id: str,
        data_type: GoogleHealthDataType,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        max_days = 14 if data_type.name in SHORT_ROLLUP_DATA_TYPES else 90
        chunk_start = date_from
        while chunk_start < date_to:
            chunk_end = min(chunk_start + timedelta(days=max_days), date_to)
            page_token: str | None = None
            seen_page_tokens: set[str] = set()
            while True:
                response = self._client.rollup(
                    connection_id,
                    data_type.name,
                    date_from=chunk_start,
                    date_to=chunk_end,
                    window_size_seconds=INTERVAL_ROLLUP_WINDOW_SECONDS,
                    page_token=page_token,
                )
                responses.append(response)
                next_page_token = response.get("nextPageToken")
                if not isinstance(next_page_token, str) or not next_page_token:
                    break
                if next_page_token in seen_page_tokens:
                    raise RuntimeError("google_health_repeated_page_token")
                seen_page_tokens.add(next_page_token)
                page_token = next_page_token
            chunk_start = chunk_end
        return responses


def _build_filter(
    data_type: GoogleHealthDataType,
    date_from: date,
    date_to: date,
    *,
    timezone: ZoneInfo | None = None,
) -> str:
    """record種別に対応するGoogle Health filter式を返す。"""
    if data_type.record_kind is RecordKind.DAILY:
        field = f"{data_type.filter_name}.date"
        start = date_from.isoformat()
        end = date_to.isoformat()
    elif data_type.record_kind is RecordKind.SAMPLE:
        field = f"{data_type.filter_name}.sample_time.physical_time"
        start = local_date_start_rfc3339(date_from, timezone or ZoneInfo("UTC"))
        end = local_date_start_rfc3339(date_to, timezone or ZoneInfo("UTC"))
    elif data_type.record_kind is RecordKind.SESSION:
        if data_type.name == "sleep":
            field = "sleep.interval.end_time"
            start = local_date_start_rfc3339(date_from, timezone or ZoneInfo("UTC"))
            end = local_date_start_rfc3339(date_to, timezone or ZoneInfo("UTC"))
        else:
            field = f"{data_type.filter_name}.interval.civil_start_time"
            start = date_from.isoformat()
            end = date_to.isoformat()
    else:
        field = f"{data_type.filter_name}.interval.start_time"
        start = local_date_start_rfc3339(date_from, timezone or ZoneInfo("UTC"))
        end = local_date_start_rfc3339(date_to, timezone or ZoneInfo("UTC"))
    return f'{field} >= "{start}" AND {field} < "{end}"'
