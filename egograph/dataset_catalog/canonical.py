"""Parquet の canonical type 変換ヘルパー。

Pipelines は pyarrow で出力を検証し、Backend は DuckDB で fixture を検証する。
両者が同じ型契約を参照できるよう、canonical type 文字列と各エンジンの型名を
正規化する関数を提供する。
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

STRING = "string"
INTEGER = "integer"
FLOAT = "float"
BOOLEAN = "boolean"
TIMESTAMP = "timestamp"
DATE = "date"
LIST_STRING = "list<string>"
NULL = "null"

VALID_CANONICAL_TYPES = frozenset(
    {
        STRING,
        INTEGER,
        FLOAT,
        BOOLEAN,
        TIMESTAMP,
        DATE,
        LIST_STRING,
        NULL,
    }
)

_DUCKDB_TYPE_MAP: dict[str, str] = {
    "VARCHAR": STRING,
    "TEXT": STRING,
    "STRING": STRING,
    "BIGINT": INTEGER,
    "INTEGER": INTEGER,
    "INT": INTEGER,
    "SMALLINT": INTEGER,
    "TINYINT": INTEGER,
    "HUGEINT": INTEGER,
    "UBIGINT": INTEGER,
    "UINTEGER": INTEGER,
    "USMALLINT": INTEGER,
    "UTINYINT": INTEGER,
    "DOUBLE": FLOAT,
    "FLOAT": FLOAT,
    "REAL": FLOAT,
    "BOOLEAN": BOOLEAN,
    "TIMESTAMP": TIMESTAMP,
    "TIMESTAMP WITH TIME ZONE": TIMESTAMP,
    "TIMESTAMPTZ": TIMESTAMP,
    "DATE": DATE,
    "VARCHAR[]": LIST_STRING,
    "TEXT[]": LIST_STRING,
    "STRING[]": LIST_STRING,
}


def arrow_type_to_canonical(arrow_type: Any) -> str:
    """pyarrow DataType を canonical type 文字列へ変換する。"""
    if pa.types.is_null(arrow_type):
        return NULL
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return STRING
    if pa.types.is_integer(arrow_type):
        return INTEGER
    if pa.types.is_floating(arrow_type):
        return FLOAT
    if pa.types.is_boolean(arrow_type):
        return BOOLEAN
    if pa.types.is_timestamp(arrow_type):
        return TIMESTAMP
    if pa.types.is_date(arrow_type):
        return DATE
    if pa.types.is_list(arrow_type) and (
        pa.types.is_string(arrow_type.value_type)
        or pa.types.is_large_string(arrow_type.value_type)
    ):
        return LIST_STRING
    return str(arrow_type)


def duckdb_type_to_canonical(duckdb_type: str) -> str:
    """DuckDB の column_type 文字列を canonical type 文字列へ変換する。"""
    normalized = duckdb_type.strip().upper()
    return _DUCKDB_TYPE_MAP.get(normalized, normalized)


def type_mismatch(expected: str, actual: str) -> str | None:
    """canonical 型の差分を返す。許容される場合は None。

    - 実型が null（未投入カラム）はどの expected にも許容する
    """
    if actual == NULL:
        return None
    if expected == actual:
        return None
    return f"expected {expected}, got {actual}"
