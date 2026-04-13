"""DuckDB 生SQL実行ツール。"""

from typing import Any

from backend.config import R2Config
from backend.domain.models.tool import ToolBase
from backend.infrastructure.database.connection import DuckDBConnection


class DataQueryTool(ToolBase):
    """DuckDBの生SQLを実行するツール。"""

    MAX_ROWS = 1000

    def __init__(self, r2_config: R2Config):
        """DataQueryToolを初期化します。

        Args:
            r2_config: DuckDB接続に利用するR2設定
        """
        self.r2_config = r2_config

    @property
    def name(self) -> str:
        return "data_query"

    @property
    def description(self) -> str:
        return "DuckDBの生SQLクエリを実行するツールです。SELECT文のみ実行できます。"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "実行するSQLクエリ（SELECT文のみ）",
                },
                "params": {
                    "type": "array",
                    "description": "SQLプレースホルダのパラメータ（オプション）",
                    "items": {},
                },
            },
            "required": ["sql"],
        }

    def execute(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        """SELECTクエリを実行して結果を返します。"""
        self._validate_sql(sql)

        limited_sql = f"SELECT * FROM ({sql}) AS _sub LIMIT {self.MAX_ROWS + 1}"

        with DuckDBConnection(self.r2_config) as conn:
            result = conn.execute(limited_sql, params or [])
            column_names = [column[0] for column in result.description]
            rows = result.fetchall()

        if len(rows) > self.MAX_ROWS:
            raise ValueError(f"Query returned too many rows (limit: {self.MAX_ROWS})")

        if not rows:
            return []

        return [
            {column_name: row[index] for index, column_name in enumerate(column_names)}
            for row in rows
        ]

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """SELECT文のみ許可する。"""
        normalized_sql = sql.strip().upper()
        first_word = normalized_sql.split(maxsplit=1)[0] if normalized_sql else ""

        if not normalized_sql.startswith("SELECT"):
            raise ValueError(f"Only SELECT queries are allowed. Got: {first_word}")
