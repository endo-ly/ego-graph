"""Tools/Browser History層のテスト。"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from backend.domain.tools.browser_history.page_views import (
    GetPageViewsTool,
    GetTopDomainsTool,
)


class TestGetPageViewsTool:
    """GetPageViewsTool のテスト。"""

    def test_name_property(self):
        tool = GetPageViewsTool(MagicMock())
        assert tool.name == "get_page_views"

    def test_input_schema_includes_filters(self):
        tool = GetPageViewsTool(MagicMock())

        schema = tool.input_schema

        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "browser" in schema["properties"]
        assert "profile" in schema["properties"]
        assert "limit" in schema["properties"]

    def test_execute_validates_and_delegates(self):
        repository = MagicMock()
        repository.get_page_views.return_value = [{"page_view_id": "pv_1"}]
        tool = GetPageViewsTool(repository)

        result = tool.execute(
            start_date="2026-03-20",
            end_date="2026-03-22",
            browser="edge",
            profile="Default",
            limit=20,
        )

        assert result == [{"page_view_id": "pv_1"}]
        repository.get_page_views.assert_called_once()
        call_args = repository.get_page_views.call_args
        assert call_args.kwargs["start_date"] == date(2026, 3, 20)
        assert call_args.kwargs["end_date"] == date(2026, 3, 22)
        assert call_args.kwargs["browser"] == "edge"
        assert call_args.kwargs["profile"] == "Default"
        assert call_args.kwargs["limit"] == 20

    def test_execute_with_invalid_date_raises_error(self):
        tool = GetPageViewsTool(MagicMock())

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="bad-date", end_date="2026-03-22")


class TestGetTopDomainsTool:
    """GetTopDomainsTool のテスト。"""

    def test_name_property(self):
        tool = GetTopDomainsTool(MagicMock())
        assert tool.name == "get_top_domains"

    def test_input_schema_includes_filters(self):
        tool = GetTopDomainsTool(MagicMock())

        schema = tool.input_schema

        assert schema["type"] == "object"
        assert "start_date" in schema["properties"]
        assert "end_date" in schema["properties"]
        assert "browser" in schema["properties"]
        assert "profile" in schema["properties"]
        assert "limit" in schema["properties"]

    def test_execute_validates_and_delegates(self):
        repository = MagicMock()
        repository.get_top_domains.return_value = [{"domain": "github.com"}]
        tool = GetTopDomainsTool(repository)

        result = tool.execute(
            start_date="2026-03-20",
            end_date="2026-03-22",
            browser="edge",
            profile="Default",
            limit=10,
        )

        assert result == [{"domain": "github.com"}]
        repository.get_top_domains.assert_called_once()
        call_args = repository.get_top_domains.call_args
        assert call_args.kwargs["browser"] == "edge"
        assert call_args.kwargs["profile"] == "Default"
        assert call_args.kwargs["limit"] == 10

    def test_execute_with_invalid_date_raises_error(self):
        tool = GetTopDomainsTool(MagicMock())

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="bad-date", end_date="2026-03-22")
