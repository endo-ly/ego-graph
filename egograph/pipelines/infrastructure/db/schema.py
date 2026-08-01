"""SQLite schema bootstrap。"""

import sqlite3

from pipelines.infrastructure.db.migrations import run_migrations


def initialize_schema(conn: sqlite3.Connection) -> None:
    """pipelines 管理テーブルを作成し未適用の migration を適用する。"""
    run_migrations(conn)
