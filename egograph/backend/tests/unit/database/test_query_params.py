"""QueryParams と execute_query のテスト。"""

from dataclasses import FrozenInstanceError
from datetime import date, datetime
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from backend.config import R2Config
from backend.infrastructure.database.query_params import (
    QueryParams,
    _normalize_value,
    execute_query,
)


class TestQueryParams:
    """QueryParams dataclass のテスト。"""

    def test_query_params_fields(self):
        """QueryParams が必要なフィールドを持つことを確認。"""
        # Arrange
        r2_config = R2Config.model_construct()
        conn = MagicMock()

        # Act
        params = QueryParams(
            conn=conn,
            r2_config=r2_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            utc_start=datetime(2024, 1, 1),
            utc_end=datetime(2024, 2, 1),
        )

        # Assert
        assert params.conn is conn
        assert params.r2_config is r2_config
        assert params.start_date == date(2024, 1, 1)
        assert params.end_date == date(2024, 1, 31)
        assert params.utc_start == datetime(2024, 1, 1)
        assert params.utc_end == datetime(2024, 2, 1)
        assert params.tz_name == "UTC"

    def test_query_params_frozen(self):
        """frozen=True によりインスタンスの変更が禁止されることを確認。"""
        # Arrange
        r2_config = R2Config.model_construct()
        conn = MagicMock()
        params = QueryParams(
            conn=conn,
            r2_config=r2_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            utc_start=datetime(2024, 1, 1),
            utc_end=datetime(2024, 2, 1),
        )

        # Act & Assert
        with pytest.raises(FrozenInstanceError):
            params.tz_name = "Asia/Tokyo"

    def test_query_params_r2_config_required(self):
        """r2_config を省略すると TypeError が発生することを確認。"""
        # Arrange
        conn = MagicMock()

        # Act & Assert
        with pytest.raises(TypeError):
            QueryParams(  # type: ignore[call-arg]
                conn=conn,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                utc_start=datetime(2024, 1, 1),
                utc_end=datetime(2024, 2, 1),
            )


class TestNormalizeValue:
    """_normalize_value のテスト。"""

    def test_normalize_ndarray(self):
        """np.ndarray をリストに変換。"""
        # Arrange
        arr = np.array([1, 2, 3])

        # Act
        result = _normalize_value(arr)

        # Assert
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_normalize_integer(self):
        """np.integer を int に変換。"""
        # Arrange
        val = np.int64(42)

        # Act
        result = _normalize_value(val)

        # Assert
        assert result == 42
        assert isinstance(result, int)

    def test_normalize_float(self):
        """np.floating を float に変換。"""
        # Arrange
        val = np.float64(3.14)

        # Act
        result = _normalize_value(val)

        # Assert
        assert result == 3.14
        assert isinstance(result, float)

    def test_normalize_bool(self):
        """np.bool_ を bool に変換。"""
        # Arrange
        val = np.bool_(True)

        # Act
        result = _normalize_value(val)

        # Assert
        assert result is True
        assert isinstance(result, bool)

    def test_normalize_plain_types_unchanged(self):
        """Python標準型は変換されずそのまま返る。"""
        # Arrange
        values = [42, 3.14, True, "hello", None, [1, 2, 3], {"a": 1}]

        # Act & Assert
        for val in values:
            assert _normalize_value(val) is val


class TestExecuteQuery:
    """execute_query のテスト。"""

    def test_execute_query_normal(self):
        """通常のクエリ実行で辞書のリストが返ることを確認。"""
        # Arrange
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_df = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
        mock_result.df.return_value = mock_df
        mock_conn.execute.return_value = mock_result

        # Act
        result = execute_query(mock_conn, "SELECT * FROM users")

        # Assert
        mock_conn.execute.assert_called_once_with("SELECT * FROM users", [])
        assert result == [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]

    def test_execute_query_numpy_conversion(self):
        """numpy 型が Python 標準型に変換されることを確認。"""
        # Arrange
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_df = pd.DataFrame(
            {
                "id": np.int64([1, 2]),
                "score": np.float64([95.5, 87.3]),
                "is_active": np.bool_([True, False]),
                "tags": [np.array(["a", "b"]), np.array(["c"])],
            }
        )
        mock_result.df.return_value = mock_df
        mock_conn.execute.return_value = mock_result

        # Act
        result = execute_query(mock_conn, "SELECT * FROM data")

        # Assert
        assert len(result) == 2
        assert result[0] == {
            "id": 1,
            "score": 95.5,
            "is_active": True,
            "tags": ["a", "b"],
        }
        assert result[1] == {
            "id": 2,
            "score": 87.3,
            "is_active": False,
            "tags": ["c"],
        }
        # 型が正しく変換されていることを確認
        assert isinstance(result[0]["id"], int)
        assert isinstance(result[0]["score"], float)
        assert isinstance(result[0]["is_active"], bool)
        assert isinstance(result[0]["tags"], list)

    def test_execute_query_empty_result(self):
        """結果が空の場合、空リストが返ることを確認。"""
        # Arrange
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_df = pd.DataFrame()
        mock_result.df.return_value = mock_df
        mock_conn.execute.return_value = mock_result

        # Act
        result = execute_query(mock_conn, "SELECT * FROM empty_table")

        # Assert
        mock_conn.execute.assert_called_once_with(
            "SELECT * FROM empty_table", []
        )
        assert result == []
