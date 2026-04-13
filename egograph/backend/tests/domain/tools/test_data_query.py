"""DataQueryToolのテスト。"""

from collections.abc import Generator
from unittest.mock import patch

import duckdb
import pytest
from backend.domain.tools.data_query import DataQueryTool


class _DuckDBConnectionStub:
    """テスト用のDuckDBConnectionスタブ。"""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self._conn = conn

    def __enter__(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


@pytest.fixture
def tool(mock_r2_config) -> DataQueryTool:
    """テスト対象のツール。"""
    return DataQueryTool(mock_r2_config)


@pytest.fixture
def patched_duckdb_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """実DuckDB接続をDuckDBConnectionに差し替える。"""
    conn = duckdb.connect(":memory:")

    with patch(
        "backend.domain.tools.data_query.DuckDBConnection",
        side_effect=lambda *_args, **_kwargs: _DuckDBConnectionStub(conn),
    ):
        yield conn

    conn.close()


def test_execute_select_returns_results(tool, patched_duckdb_connection):
    result = tool.execute("SELECT 1 AS num")

    assert result == [{"num": 1}]


def test_execute_select_with_params(tool, patched_duckdb_connection):
    result = tool.execute("SELECT ? AS val", params=[42])

    assert result == [{"val": 42}]


def test_execute_select_empty_result(tool, patched_duckdb_connection):
    patched_duckdb_connection.execute("CREATE TABLE empty_table (id INTEGER)")

    result = tool.execute("SELECT * FROM empty_table")

    assert result == []


def test_execute_rejects_drop_table(tool):
    with pytest.raises(
        ValueError, match=r"Only SELECT queries are allowed\. Got: DROP"
    ):
        tool.execute("DROP TABLE x")


def test_execute_rejects_insert(tool):
    with pytest.raises(
        ValueError, match=r"Only SELECT queries are allowed\. Got: INSERT"
    ):
        tool.execute("INSERT INTO x VALUES(1)")


def test_execute_rejects_delete(tool):
    with pytest.raises(
        ValueError, match=r"Only SELECT queries are allowed\. Got: DELETE"
    ):
        tool.execute("DELETE FROM x")


def test_execute_rejects_update(tool):
    with pytest.raises(
        ValueError, match=r"Only SELECT queries are allowed\. Got: UPDATE"
    ):
        tool.execute("UPDATE x SET y=1")


def test_execute_rejects_alter(tool):
    with pytest.raises(
        ValueError, match=r"Only SELECT queries are allowed\. Got: ALTER"
    ):
        tool.execute("ALTER TABLE x ADD y INT")


def test_execute_rejects_create(tool):
    with pytest.raises(
        ValueError, match=r"Only SELECT queries are allowed\. Got: CREATE"
    ):
        tool.execute("CREATE TABLE x (id INT)")


def test_execute_case_insensitive_rejection(tool):
    with pytest.raises(
        ValueError, match=r"Only SELECT queries are allowed\. Got: DROP"
    ):
        tool.execute("drop table x")


def test_execute_limit_enforced(tool, patched_duckdb_connection):
    success_result = tool.execute("SELECT * FROM range(1000) AS t(num)")

    assert len(success_result) == 1000

    with pytest.raises(
        ValueError, match=r"Query returned too many rows \(limit: 1000\)"
    ):
        tool.execute("SELECT * FROM range(1001) AS t(num)")


def test_name_and_schema(tool):
    assert tool.name == "data_query"
    assert "sql" in tool.input_schema["properties"]
