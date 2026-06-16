"""Google Health REST APIとMCP公開の統合テスト。"""

import asyncio
import json
from unittest.mock import patch

from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from backend.dependencies import get_google_health_daily_summary_use_case
from backend.infrastructure.repositories.google_health_repository import (
    GoogleHealthRepository,
)
from backend.mcp_server import create_mcp_server
from backend.usecases.google_health import GetGoogleHealthDailySummaryUseCase


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
    """MCP一覧にGoogle Health日次サマリツールを含む。"""
    server = create_mcp_server(mock_backend_config)
    handler = server._mcp_server.request_handlers[ListToolsRequest]

    result = asyncio.run(handler(ListToolsRequest(method="tools/list"))).root

    assert "get_google_health_daily_summary" in [tool.name for tool in result.tools]


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
