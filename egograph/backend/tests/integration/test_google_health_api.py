"""Google Health REST APIとMCP公開の統合テスト。"""

import asyncio
import json
from unittest.mock import patch

from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from backend.dependencies import (
    get_google_health_daily_metrics_use_case,
    get_google_health_daily_summary_use_case,
    get_google_health_record_use_case,
    get_google_health_sessions_use_case,
    get_google_health_timeseries_use_case,
)
from backend.infrastructure.repositories.google_health_repository import (
    GoogleHealthRepository,
)
from backend.mcp_server import create_mcp_server
from backend.usecases.google_health import (
    GetGoogleHealthDailyMetricsUseCase,
    GetGoogleHealthDailySummaryUseCase,
    GetGoogleHealthRecordUseCase,
    GetGoogleHealthSessionsUseCase,
    GetGoogleHealthTimeseriesUseCase,
)


class FakeGoogleHealthRepository:
    """APIテスト用Google Health repository。"""

    def get_daily_summary(self, start_date, end_date):
        return [
            {
                "date": start_date,
                "steps": 8000.0,
                "distance": None,
                "total_calories": None,
                "active_energy_burned": None,
                "active_minutes": None,
                "active_zone_minutes": None,
                "resting_heart_rate": 60.0,
                "daily_hrv": 42.0,
                "daily_oxygen_saturation": 97.0,
                "daily_respiratory_rate": 14.0,
                "sleep_duration": 25200.0,
                "daily_vo2_max": None,
            }
        ]

    def get_daily_metrics(self, start_date, end_date, data_type=None):
        return [
            {
                "date": start_date,
                "data_type": data_type or "heart-rate",
                "metric_name": "heart_rate",
                "value": 72.0,
                "unit": "bpm",
            }
        ]

    def get_timeseries(self, data_type, start_at, end_at, metric=None):
        return [
            {
                "measured_at_utc": start_at.replace(tzinfo=None),
                "metric_name": metric or "heart_rate",
                "value": 72.0,
                "unit": "bpm",
            }
        ]

    def get_sessions(self, start_date, end_date, data_type=None):
        return [
            {
                "record_id": "rec-sleep",
                "data_type": data_type or "sleep",
                "session_id": "sleep-1",
                "started_at_utc": "2026-06-01T00:00:00Z",
                "ended_at_utc": "2026-06-01T08:00:00Z",
                "duration_seconds": 28800,
                "session_type": "sleep",
            }
        ]

    def get_record(self, record_id):
        return {
            "record_id": record_id,
            "source_record_id": None,
            "connection_id": "connection-1",
            "data_type": "heart-rate",
            "record_kind": "sample",
            "record_date": "2026-06-01",
            "payload_json": '{"beatsPerMinute":72}',
            "device_family": "fitbit_air",
            "raw_ref": "raw/example.json",
            "ingested_at_utc": "2026-06-01T00:00:00Z",
        }


def test_daily_summary_api_returns_health_metrics(test_client):
    """REST APIが日次健康サマリを返す。"""
    test_client.app.dependency_overrides[get_google_health_daily_summary_use_case] = (
        lambda: GetGoogleHealthDailySummaryUseCase(FakeGoogleHealthRepository())
    )

    response = test_client.get(
        "/v1/data/google-health/daily-summary"
        "?start_date=2026-06-01&end_date=2026-06-02",
        headers={"X-API-Key": "test-backend-key"},
    )

    assert response.status_code == 200
    assert response.json()[0]["date"] == "2026-06-01"
    assert response.json()[0]["steps"] == 8000.0
    assert response.json()[0]["daily_vo2_max"] is None


def test_mcp_registry_includes_google_health_tool(mock_backend_config):
    """MCP一覧にGoogle Healthの5 query toolを含む。"""
    server = create_mcp_server(mock_backend_config)
    handler = server._mcp_server.request_handlers[ListToolsRequest]

    result = asyncio.run(handler(ListToolsRequest(method="tools/list"))).root

    names = {tool.name for tool in result.tools}
    assert {
        "get_google_health_daily_summary",
        "get_google_health_daily_metrics",
        "get_google_health_timeseries",
        "get_google_health_sessions",
        "get_google_health_record",
    } <= names


def test_detail_apis_use_the_same_query_usecases(test_client):
    """新4 query endpointがcolumnar/detail結果を返す。"""
    repository = FakeGoogleHealthRepository()

    def daily_metrics_use_case():
        return GetGoogleHealthDailyMetricsUseCase(repository)

    def timeseries_use_case():
        return GetGoogleHealthTimeseriesUseCase(repository)

    def sessions_use_case():
        return GetGoogleHealthSessionsUseCase(repository)

    def record_use_case():
        return GetGoogleHealthRecordUseCase(repository)

    test_client.app.dependency_overrides.update(
        {
            get_google_health_daily_metrics_use_case: daily_metrics_use_case,
            get_google_health_timeseries_use_case: timeseries_use_case,
            get_google_health_sessions_use_case: sessions_use_case,
            get_google_health_record_use_case: record_use_case,
        }
    )
    headers = {"X-API-Key": "test-backend-key"}

    # Act
    daily_metrics = test_client.get(
        "/v1/data/google-health/daily-metrics?start_date=2026-06-01&end_date=2026-06-01",
        headers=headers,
    )
    timeseries = test_client.get(
        "/v1/data/google-health/timeseries?data_type=heart-rate&"
        "start_at=2026-06-01T00:00:00Z&end_at=2026-06-01T01:00:00Z&"
        "resolution=raw&metric=heart_rate",
        headers=headers,
    )
    sessions = test_client.get(
        "/v1/data/google-health/sessions?data_type=sleep&"
        "start_date=2026-06-01&end_date=2026-06-01",
        headers=headers,
    )
    record = test_client.get(
        "/v1/data/google-health/records/rec-sleep",
        headers=headers,
    )

    # Assert
    assert daily_metrics.status_code == 200
    assert daily_metrics.json()["columns"] == ["date", "metric", "value", "unit"]
    assert timeseries.status_code == 200
    assert timeseries.json()["series"]["columns"] == ["time", "value"]
    assert timeseries.json()["metric"] == "heart_rate"
    assert sessions.status_code == 200
    assert sessions.json()["rows"][0][0] == "rec-sleep"
    assert record.status_code == 200
    assert record.json() == {
        "id": "rec-sleep",
        "type": "heart-rate",
        "kind": "sample",
        "date": "2026-06-01",
        "payload": {"beatsPerMinute": 72},
    }


def test_mcp_google_health_tool_returns_json(mock_backend_config):
    """MCP経由でGoogle Health日次サマリをJSONとして返す。"""
    payload = [
        {
            "date": "2026-06-01",
            "steps": 8000.0,
            "daily_hrv": 42.0,
        }
    ]
    with patch.object(
        GoogleHealthRepository,
        "get_daily_summary",
        return_value=payload,
    ):
        server = create_mcp_server(mock_backend_config)
        handler = server._mcp_server.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="get_google_health_daily_summary",
                arguments={
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-02",
                },
            ),
        )

        result = asyncio.run(handler(request)).root

    assert result.isError is False
    assert json.loads(result.content[0].text) == payload


def test_mcp_google_health_detail_tool_uses_columnar_result(mock_backend_config):
    """MCP詳細QueryがRESTと同じUseCase結果をJSON化する。"""
    payload = [
        {
            "date": "2026-06-01",
            "data_type": "heart-rate",
            "metric_name": "heart_rate",
            "value": 72.0,
            "unit": "bpm",
        }
    ]
    with patch.object(
        GoogleHealthRepository,
        "get_daily_metrics",
        return_value=payload,
    ):
        server = create_mcp_server(mock_backend_config)
        handler = server._mcp_server.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="get_google_health_daily_metrics",
                arguments={
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-01",
                },
            ),
        )

        result = asyncio.run(handler(request)).root

    assert result.isError is False
    assert json.loads(result.content[0].text) == {
        "columns": ["date", "metric", "value", "unit"],
        "rows": [["2026-06-01", "heart_rate", 72.0, "bpm"]],
    }
