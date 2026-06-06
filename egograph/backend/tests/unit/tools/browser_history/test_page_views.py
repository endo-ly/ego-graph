"""Tools/Browser History層のテスト。"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from backend.domain.tools.browser_history.page_views import (
    GetPageViewsTool,
    GetTopDomainsTool,
)


def _mock_conn_ctx():
    """DuckDBConnection のコンテキストマネージャーモックを返す。"""
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx


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
        assert "include_reload" in schema["properties"]
        assert schema["properties"]["include_reload"]["type"] == "boolean"

    @patch("backend.domain.tools.browser_history.page_views.DuckDBConnection")
    def test_execute_validates_and_delegates(self, MockConn):
        MockConn.return_value = _mock_conn_ctx()

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
        assert call_args.kwargs["include_reload"] is None

    @patch("backend.domain.tools.browser_history.page_views.DuckDBConnection")
    def test_execute_passes_include_reload_true(self, MockConn):
        """include_reload=True をリポジトリまで伝播する。"""
        MockConn.return_value = _mock_conn_ctx()

        repository = MagicMock()
        repository.get_page_views.return_value = []
        tool = GetPageViewsTool(repository)

        tool.execute(
            start_date="2026-03-20",
            end_date="2026-03-22",
            include_reload=True,
        )

        assert repository.get_page_views.call_args.kwargs["include_reload"] is True

    @patch("backend.domain.tools.browser_history.page_views.DuckDBConnection")
    def test_execute_passes_include_reload_false(self, MockConn):
        """include_reload=False をリポジトリまで伝播する。"""
        MockConn.return_value = _mock_conn_ctx()

        repository = MagicMock()
        repository.get_page_views.return_value = []
        tool = GetPageViewsTool(repository)

        tool.execute(
            start_date="2026-03-20",
            end_date="2026-03-22",
            include_reload=False,
        )

        assert repository.get_page_views.call_args.kwargs["include_reload"] is False

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
        assert "include_reload" in schema["properties"]
        assert schema["properties"]["include_reload"]["type"] == "boolean"

    @patch("backend.domain.tools.browser_history.page_views.DuckDBConnection")
    def test_execute_validates_and_delegates(self, MockConn):
        MockConn.return_value = _mock_conn_ctx()

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
        assert call_args.kwargs["include_reload"] is None

    @patch("backend.domain.tools.browser_history.page_views.DuckDBConnection")
    def test_execute_passes_include_reload_true(self, MockConn):
        """top_domains でも include_reload=True をリポジトリまで伝播する。"""
        MockConn.return_value = _mock_conn_ctx()

        repository = MagicMock()
        repository.get_top_domains.return_value = []
        tool = GetTopDomainsTool(repository)

        tool.execute(
            start_date="2026-03-20",
            end_date="2026-03-22",
            include_reload=True,
        )

        assert repository.get_top_domains.call_args.kwargs["include_reload"] is True

    @patch("backend.domain.tools.browser_history.page_views.DuckDBConnection")
    def test_execute_passes_include_reload_false(self, MockConn):
        """top_domains でも include_reload=False をリポジトリまで伝播する。"""
        MockConn.return_value = _mock_conn_ctx()

        repository = MagicMock()
        repository.get_top_domains.return_value = []
        tool = GetTopDomainsTool(repository)

        tool.execute(
            start_date="2026-03-20",
            end_date="2026-03-22",
            include_reload=False,
        )

        assert repository.get_top_domains.call_args.kwargs["include_reload"] is False

    def test_execute_with_invalid_date_raises_error(self):
        tool = GetTopDomainsTool(MagicMock())

        with pytest.raises(ValueError, match="invalid_start_date"):
            tool.execute(start_date="bad-date", end_date="2026-03-22")
