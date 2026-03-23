#!/usr/bin/env python3
"""Cloudflare R2 上の Parquet を DuckDB で直接クエリする。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from backend.config import BackendConfig


def build_s3_path(bucket_name: str, dataset: str) -> str:
    """bucket 配下の相対パスを s3 URI に変換する。"""
    normalized = dataset.lstrip("/")
    if normalized.startswith("s3://"):
        return normalized
    return f"s3://{bucket_name}/{normalized}"


def create_connection() -> tuple[duckdb.DuckDBPyConnection, str]:
    """R2 設定済み DuckDB 接続を返す。"""
    config = BackendConfig.from_env()
    if not config.r2:
        raise ValueError("R2 configuration is missing.")

    r2 = config.r2
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    conn.execute(
        """
        CREATE SECRET (
            TYPE S3,
            KEY_ID ?,
            SECRET ?,
            REGION 'auto',
            ENDPOINT ?,
            URL_STYLE 'path'
        );
        """,
        [
            r2.access_key_id,
            r2.secret_access_key.get_secret_value(),
            r2.endpoint_url.replace("https://", ""),
        ],
    )
    return conn, r2.bucket_name


def print_rows(rows: list[tuple[object, ...]]) -> None:
    """行データを素朴に表示する。"""
    for row in rows:
        print(row)


def quote_sql_string(value: str) -> str:
    """SQL 文字列リテラルとして安全に埋め込む。"""
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    """CLI エントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="Query Parquet files on Cloudflare R2 through DuckDB."
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Bucket-relative parquet glob, e.g. events/browser_history/page_views/**/*.parquet",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print schema before any data query.",
    )
    parser.add_argument(
        "--count",
        action="store_true",
        help="Print total row count.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Row limit for the default preview query.",
    )
    parser.add_argument(
        "--sql",
        help="Custom SQL using the temp view name `dataset`.",
    )
    args = parser.parse_args()

    conn, bucket_name = create_connection()
    parquet_path = build_s3_path(bucket_name, args.dataset)

    try:
        conn.execute(
            f"CREATE VIEW dataset AS SELECT * FROM read_parquet({quote_sql_string(parquet_path)})"
        )

        print(f"PATH {parquet_path}")

        if args.describe:
            print("SCHEMA")
            print_rows(conn.execute("DESCRIBE dataset").fetchall())

        if args.count:
            count = conn.execute("SELECT COUNT(*) FROM dataset").fetchone()
            print(f"COUNT {count[0] if count else 0}")

        sql = args.sql or f"SELECT * FROM dataset LIMIT {args.limit}"
        print("QUERY")
        print(sql)
        print("ROWS")
        print_rows(conn.execute(sql).fetchall())
        return 0
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
