"""統合クエリパラメータとクエリ実行ユーティリティ。

numpy/pandas型の自動変換によるJSONシリアライズ対応を含みます。
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import duckdb
import numpy as np

from backend.config import R2Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryParams:
    """クエリ用の共通パラメータ（不変）。

    Attributes:
        conn: DuckDBコネクション
        r2_config: R2設定（必須）
        start_date: 検索開始日
        end_date: 検索終了日
        utc_start: UTC開始時刻
        utc_end: UTC終了時刻
        tz_name: タイムゾーン名（デフォルト: UTC）
    """

    conn: duckdb.DuckDBPyConnection
    r2_config: R2Config
    start_date: date
    end_date: date
    utc_start: datetime
    utc_end: datetime
    tz_name: str = "UTC"


def _normalize_value(value: Any) -> Any:
    """numpy/pandas型をPython標準型に変換します。

    Args:
        value: 変換対象の値

    Returns:
        Python標準型に変換された値
    """
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.int64, np.int32)):
        return int(value)
    if isinstance(value, (np.floating, np.float64, np.float32)):
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def execute_query(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    """SQLクエリを実行し、結果を辞書のリストとして返します。

    numpy/pandas型をPython標準型に変換することで、JSONシリアライズに対応します。

    Args:
        conn: DuckDBコネクション
        sql: 実行するSQLクエリ
        params: SQLパラメータ（オプション）

    Returns:
        クエリ結果（辞書のリスト）

    Raises:
        duckdb.Error: SQLクエリ実行に失敗した場合
    """
    result = conn.execute(sql, params or [])
    df = result.df()
    records = df.to_dict(orient="records")
    return [
        {k: _normalize_value(v) for k, v in record.items()} for record in records
    ]
