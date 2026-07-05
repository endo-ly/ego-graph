"""``GetDailyTimelineTool`` のバリデーションと execute の単体テスト。

REST と MCP で共有する validation ロジックを検証する。
"""

from datetime import date
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from backend.domain.tools.timeline.daily import (
    GetDailyTimelineTool,
    resolve_default_timezone,
)

JST = ZoneInfo("Asia/Tokyo")


def _tool() -> GetDailyTimelineTool:
    repository = MagicMock()
    repository.build_daily_timeline.return_value = {"items": []}
    return GetDailyTimelineTool(repository, default_timezone=JST)


class TestExecuteValidation:
    """execute が repository に正規化済みの入力を渡すことのテスト。"""

    def test_passes_validated_inputs_to_repository(self):
        tool = _tool()
        tool.execute(
            date="2026-06-28",
            timezone="Asia/Tokyo",
            sources=["spotify", "youtube"],
            gap_minutes=90,
            include_correlations=False,
            include_raw_refs=True,
            limit=10,
        )
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["date_local"] == date(2026, 6, 28)
        assert kwargs["timezone"] == JST
        assert kwargs["sources"] == {"spotify", "youtube"}
        assert kwargs["gap_minutes"] == 90
        assert kwargs["include_correlations"] is False
        assert kwargs["include_raw_refs"] is True
        assert kwargs["limit"] == 10

    def test_default_timezone_used_when_omitted(self):
        tool = _tool()
        tool.execute(date="2026-06-28")
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["timezone"] == JST
        assert kwargs["sources"] == set()
        assert kwargs["gap_minutes"] == 120
        assert kwargs["include_correlations"] is True
        assert kwargs["include_raw_refs"] is False
        assert kwargs["limit"] == 500


class TestDateValidation:
    @pytest.mark.parametrize("value", ["2026-06-28", "2024-02-29"])
    def test_accepts_valid_date(self, value):
        tool = _tool()
        tool.execute(date=value)
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["date_local"] == date.fromisoformat(value)

    @pytest.mark.parametrize("value", ["2026/06/28", "not-a-date", "2026-13-01"])
    def test_rejects_invalid_date(self, value):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_date"):
            tool.execute(date=value)


class TestTimezoneValidation:
    def test_rejects_unknown_timezone(self):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_timezone"):
            tool.execute(date="2026-06-28", timezone="Not/A/Zone")

    def test_accepts_iana_timezone(self):
        tool = _tool()
        tool.execute(date="2026-06-28", timezone="America/New_York")
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["timezone"] == ZoneInfo("America/New_York")


class TestSourcesValidation:
    def test_rejects_unknown_source(self):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_sources"):
            tool.execute(date="2026-06-28", sources=["spotify", "unknown"])

    def test_accepts_all_known_sources(self):
        tool = _tool()
        tool.execute(
            date="2026-06-28",
            sources=[
                "spotify",
                "youtube",
                "browser_history",
                "github",
                "google_health",
            ],
        )
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["sources"] == {
            "spotify",
            "youtube",
            "browser_history",
            "github",
            "google_health",
        }


class TestGapMinutesValidation:
    @pytest.mark.parametrize("value", [0, 1, 120, 1440])
    def test_accepts_valid_gap_minutes(self, value):
        tool = _tool()
        tool.execute(date="2026-06-28", gap_minutes=value)

    @pytest.mark.parametrize("value", [-1, 1441])
    def test_rejects_out_of_range(self, value):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_gap_minutes"):
            tool.execute(date="2026-06-28", gap_minutes=value)

    def test_none_disables_gap(self):
        tool = _tool()
        tool.execute(date="2026-06-28", gap_minutes=None)
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["gap_minutes"] is None

    def test_accepts_numeric_string_from_rest_query(self):
        tool = _tool()
        tool.execute(date="2026-06-28", gap_minutes="120")
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["gap_minutes"] == 120

    def test_rejects_non_numeric_string(self):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_gap_minutes"):
            tool.execute(date="2026-06-28", gap_minutes="abc")


class TestLimitValidation:
    @pytest.mark.parametrize("value", [1, 500, 2000])
    def test_accepts_valid_limit(self, value):
        tool = _tool()
        tool.execute(date="2026-06-28", limit=value)

    @pytest.mark.parametrize("value", [0, 2001])
    def test_rejects_out_of_range(self, value):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_limit"):
            tool.execute(date="2026-06-28", limit=value)

    def test_accepts_numeric_string_from_rest_query(self):
        tool = _tool()
        tool.execute(date="2026-06-28", limit="100")
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["limit"] == 100

    def test_rejects_non_numeric_string(self):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_limit"):
            tool.execute(date="2026-06-28", limit="abc")


class TestBooleanValidation:
    def test_accepts_boolean_strings_from_rest_query(self):
        tool = _tool()
        tool.execute(
            date="2026-06-28",
            include_correlations="false",
            include_raw_refs="true",
        )
        kwargs = tool.repository.build_daily_timeline.call_args.kwargs
        assert kwargs["include_correlations"] is False
        assert kwargs["include_raw_refs"] is True

    def test_rejects_invalid_boolean_string(self):
        tool = _tool()
        with pytest.raises(ValueError, match="invalid_include_correlations"):
            tool.execute(date="2026-06-28", include_correlations="maybe")


class TestDefaultTimezoneResolution:
    def test_unconfigured_timezone_defaults_to_jst(self):
        assert (
            resolve_default_timezone(
                ZoneInfo("UTC"),
                timezone_configured=False,
            )
            == JST
        )

    def test_explicit_utc_is_respected(self):
        assert resolve_default_timezone(
            ZoneInfo("UTC"),
            timezone_configured=True,
        ) == ZoneInfo("UTC")


class TestInputSchemaContract:
    def test_schema_requires_date_and_lists_optional_params(self):
        schema = _tool().input_schema
        assert schema["type"] == "object"
        assert schema["required"] == ["date"]
        properties = schema["properties"]
        for field in [
            "date",
            "timezone",
            "sources",
            "gap_minutes",
            "include_correlations",
            "include_raw_refs",
            "limit",
        ]:
            assert field in properties
