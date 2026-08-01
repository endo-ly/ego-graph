"""Parquet 保存前の schema 検証。

Pipelines 各 storage の保存入口から呼び出され、Dataset Catalog の契約
（required_columns / column_types）と実 Parquet を突き合わせる。
検証失敗は常に ``ValueError``（``invalid_schema: ...``）で表現し、
各 storage が既存の失敗契約（None / failed 数 / 例外）へ変換する。
"""

from __future__ import annotations

import io
from collections.abc import Iterable

import pyarrow.parquet as pq

from dataset_catalog.canonical import arrow_type_to_canonical, type_mismatch
from dataset_catalog.catalog import DatasetDefinition


def validate_required_columns(
    definition: DatasetDefinition,
    columns: Iterable[str],
) -> None:
    """必須カラムが揃っていることを検証する。

    Args:
        definition: 契約元の DatasetDefinition
        columns: 実データのカラム名集合

    Raises:
        ValueError: 必須カラムが欠落している場合（``invalid_schema: missing_columns``）
    """
    column_set = set(columns)
    missing = [
        column for column in definition.required_columns if column not in column_set
    ]
    if missing:
        raise ValueError(
            f"invalid_schema: missing_columns: {definition.dataset_id} "
            f"<{', '.join(missing)}>"
        )


def validate_parquet_bytes(definition: DatasetDefinition, data: bytes) -> None:
    """Parquet バイト列が契約と一致することを検証する。

    pandas の内部 dtype に依存せず、バイト列から schema を取得して検証する。
    required_columns / column_types の両方を検証し、アップロード前の検証に
    使うことを想定している。読み直しは行わない。

    Args:
        definition: 契約元の DatasetDefinition
        data: アップロード前の Parquet バイト列

    Raises:
        ValueError: 契約外のカラム・型が見つかった場合
            （``invalid_schema: ...``）
    """
    if not definition.column_types:
        return
    try:
        table = pq.read_table(io.BytesIO(data))
        validate_required_columns(definition, table.schema.names)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"invalid_schema: unreadable_parquet: {definition.dataset_id}: {exc}"
        ) from exc
    for column in definition.column_types:
        expected = definition.column_types[column]
        arrow_type = table.schema.field(column).type
        actual = arrow_type_to_canonical(arrow_type)
        has_nulls = table.column(column).null_count > 0
        mismatch = type_mismatch(expected, actual, has_nulls=has_nulls)
        if mismatch is not None:
            raise ValueError(
                f"invalid_schema: {definition.dataset_id} <{column}>: {mismatch}"
            )
