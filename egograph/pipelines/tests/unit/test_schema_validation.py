"""保存前 schema validation のテスト。"""

import io
from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from dataset_catalog import DatasetDefinition
from dataset_catalog.catalog import CompactionStrategy, DataDomain, PartitionPolicy
from dataset_catalog.validation import (
    validate_parquet_bytes,
    validate_required_columns,
)


def _definition(**overrides) -> DatasetDefinition:
    base = dict(
        dataset_id="test.validation",
        provider="test",
        domain=DataDomain.EVENTS,
        path="test/validation",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.NONE,
        required_columns=("id", "created_at"),
        column_types={"id": "string", "created_at": "timestamp"},
    )
    base.update(overrides)
    return DatasetDefinition(**base)


def _coerce(schema: pa.Schema, rows: list[dict]) -> list[dict]:
    timestamp_fields = {
        field.name
        for field in schema
        if pa.types.is_timestamp(field.type)
    }
    coerced: list[dict] = []
    for row in rows:
        converted = dict(row)
        for name in timestamp_fields & converted.keys():
            converted[name] = datetime.fromisoformat(
                converted[name].replace("Z", "+00:00")
            )
        coerced.append(converted)
    return coerced


def _parquet_bytes(schema: pa.Schema, rows: list[dict]) -> bytes:
    table = pa.Table.from_pylist(_coerce(schema, rows), schema=schema)
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


SCHEMA = pa.schema(
    [
        pa.field("id", pa.string(), nullable=False),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("extra", pa.int64(), nullable=True),
    ]
)


def test_validate_required_columns_passes_when_all_present():
    """必須カラムが全て存在すれば検証を通す。"""
    validate_required_columns(_definition(), ["id", "created_at", "extra"])


def test_validate_required_columns_raises_on_missing():
    """必須カラム欠落は invalid_schema エラー。"""
    pattern = r"invalid_schema: missing_columns: test.validation <created_at>"
    with pytest.raises(ValueError, match=pattern):
        validate_required_columns(_definition(), ["id"])


def test_validate_required_columns_reports_all_missing():
    """欠落カラムを全て列挙する。"""
    pattern = r"missing_columns: test.validation <id, created_at>"
    with pytest.raises(ValueError, match=pattern):
        validate_required_columns(_definition(), [])


def test_validate_parquet_bytes_passes_on_matching_schema():
    """型が契約と一致する Parquet バイト列は検証を通す。"""
    data = _parquet_bytes(
        SCHEMA,
        [
            {"id": "a", "created_at": "2026-01-01T00:00:00Z", "extra": 1},
            {"id": "b", "created_at": "2026-01-02T00:00:00Z", "extra": None},
        ],
    )
    validate_parquet_bytes(_definition(), data)


def test_validate_parquet_bytes_passes_on_empty_table():
    """空テーブル（行なし）でも schema が正しければ検証を通す。"""
    data = _parquet_bytes(SCHEMA, [])
    validate_parquet_bytes(_definition(), data)


def test_validate_parquet_bytes_raises_on_type_mismatch():
    """契約タイプと実 Parquet 型が不一致なら invalid_schema エラー。"""
    wrong_schema = pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("created_at", pa.string(), nullable=False),
        ]
    )
    data = _parquet_bytes(
        wrong_schema,
        [{"id": "a", "created_at": "2026-01-01T00:00:00Z"}],
    )
    pattern = (
        r"invalid_schema: test.validation <created_at>: "
        r"expected timestamp, got string"
    )
    with pytest.raises(ValueError, match=pattern):
        validate_parquet_bytes(_definition(), data)


def test_validate_parquet_bytes_allows_nullable_integer_as_float():
    """pandas の int+None 拡張（float64 化）を integer 契約で許容する。"""
    float_schema = pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("count", pa.float64(), nullable=True),
        ]
    )
    integer_definition = _definition(
        required_columns=("id", "created_at", "count"),
        column_types={"id": "string", "created_at": "timestamp", "count": "integer"},
    )
    data = _parquet_bytes(
        float_schema,
        [
            {"id": "a", "created_at": "2026-01-01T00:00:00Z", "count": 1},
            {"id": "b", "created_at": "2026-01-02T00:00:00Z", "count": None},
        ],
    )
    validate_parquet_bytes(integer_definition, data)


def test_validate_parquet_bytes_rejects_float_without_nulls_for_integer():
    """null を含まない float64 は integer 契約として拒否する。"""
    float_schema = pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("count", pa.float64(), nullable=False),
        ]
    )
    integer_definition = _definition(
        required_columns=("id", "created_at", "count"),
        column_types={"id": "string", "created_at": "timestamp", "count": "integer"},
    )
    data = _parquet_bytes(
        float_schema,
        [
            {"id": "a", "created_at": "2026-01-01T00:00:00Z", "count": 1.0},
            {"id": "b", "created_at": "2026-01-02T00:00:00Z", "count": 2.5},
        ],
    )
    pattern = r"invalid_schema: test.validation <count>: expected integer, got float"
    with pytest.raises(ValueError, match=pattern):
        validate_parquet_bytes(integer_definition, data)


def test_validate_parquet_bytes_allows_extra_columns():
    """契約外の追加カラムは許容する（最低契約）。"""
    extra_schema = pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("bonus", pa.bool_(), nullable=True),
        ]
    )
    data = _parquet_bytes(
        extra_schema,
        [{"id": "a", "created_at": "2026-01-01T00:00:00Z", "bonus": True}],
    )
    validate_parquet_bytes(_definition(), data)
