"""SQLite schema migration runner。

`PRAGMA user_version` を schema version として扱い、`MIGRATIONS` に登録した
migration を番号順に適用する。各 migration は 1 トランザクションで実行し、
途中失敗時は rollback して user_version も進めない。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

Migration = Callable[[sqlite3.Connection], None]


def _migration_1_baseline(conn: sqlite3.Connection) -> None:
    """現行のデプロイ済み schema を基準 version 1 として登録する。

    空DBには全テーブルをIF NOT EXISTSで作成し、Phase 2 前の既存DBには
    ``google_health_sync_cursors`` の不足列だけを追加する。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_definitions (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            definition_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_schedules (
            schedule_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_expr TEXT NOT NULL,
            timezone TEXT NOT NULL,
            next_run_at TEXT,
            last_scheduled_at TEXT,
            FOREIGN KEY (workflow_id)
              REFERENCES workflow_definitions(workflow_id)
              ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            queued_reason TEXT NOT NULL,
            status TEXT NOT NULL,
            scheduled_at TEXT,
            queued_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            last_error_message TEXT,
            requested_by TEXT NOT NULL,
            parent_run_id TEXT,
            result_summary_json TEXT,
            FOREIGN KEY (workflow_id)
              REFERENCES workflow_definitions(workflow_id)
              ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_status_queued_at
            ON workflow_runs(status, queued_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id
            ON workflow_runs(workflow_id, queued_at)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS step_runs (
            step_run_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            step_name TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            attempt_no INTEGER NOT NULL,
            command TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            stdout_tail TEXT,
            stderr_tail TEXT,
            log_path TEXT,
            result_summary_json TEXT,
            FOREIGN KEY (run_id)
              REFERENCES workflow_runs(run_id)
              ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_step_runs_run_id_sequence
            ON step_runs(run_id, sequence_no, attempt_no)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_locks (
            lock_key TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            lease_owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS google_health_connections (
            connection_id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (
                status IN ('active', 'expired', 'revoked', 'error')
            ),
            scopes_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_error_message TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS google_health_oauth_tokens (
            connection_id TEXT PRIMARY KEY,
            access_token_encrypted BLOB NOT NULL,
            refresh_token_encrypted BLOB NOT NULL,
            expires_at TEXT NOT NULL,
            token_type TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (connection_id)
              REFERENCES google_health_connections(connection_id)
              ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS google_health_sync_cursors (
            connection_id TEXT NOT NULL,
            data_type TEXT NOT NULL,
            cursor TEXT,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'success',
            range_start TEXT,
            range_end TEXT,
            last_run_id TEXT,
            record_count INTEGER NOT NULL DEFAULT 0,
            last_error_message TEXT,
            PRIMARY KEY (connection_id, data_type),
            FOREIGN KEY (connection_id)
              REFERENCES google_health_connections(connection_id)
              ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS google_health_oauth_states (
            state_hash TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    _add_cursor_phase2_columns(conn)


_CURSOR_PHASE2_ADDITIONS: dict[str, str] = {
    "status": (
        "ALTER TABLE google_health_sync_cursors "
        "ADD COLUMN status TEXT NOT NULL DEFAULT 'success'"
    ),
    "range_start": (
        "ALTER TABLE google_health_sync_cursors ADD COLUMN range_start TEXT"
    ),
    "range_end": "ALTER TABLE google_health_sync_cursors ADD COLUMN range_end TEXT",
    "last_run_id": (
        "ALTER TABLE google_health_sync_cursors ADD COLUMN last_run_id TEXT"
    ),
    "record_count": (
        "ALTER TABLE google_health_sync_cursors "
        "ADD COLUMN record_count INTEGER NOT NULL DEFAULT 0"
    ),
    "last_error_message": (
        "ALTER TABLE google_health_sync_cursors "
        "ADD COLUMN last_error_message TEXT"
    ),
}


def _add_cursor_phase2_columns(conn: sqlite3.Connection) -> None:
    """既存のGoogle Health sync cursorへPhase 2列を不足分だけ追加する。"""
    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(google_health_sync_cursors)"
        ).fetchall()
    }
    for name, statement in _CURSOR_PHASE2_ADDITIONS.items():
        if name not in columns:
            conn.execute(statement)


# 空DBは基準 schema（version 1）から作成し、以後の変更は番号付きで追記する。
MIGRATIONS: tuple[Migration, ...] = (
    _migration_1_baseline,
)


def get_schema_version(conn: sqlite3.Connection) -> int:
    """現在の schema version を返す。"""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def run_migrations(conn: sqlite3.Connection) -> None:
    """未適用の migration を番号順に適用する。"""
    current = get_schema_version(conn)
    if current > len(MIGRATIONS):
        raise RuntimeError(
            f"schema version {current} is newer than supported "
            f"(latest={len(MIGRATIONS)})"
        )
    for version in range(current + 1, len(MIGRATIONS) + 1):
        _apply_migration(conn, version)


def _apply_migration(conn: sqlite3.Connection, version: int) -> None:
    """1 つの migration を排他トランザクションで適用する。

    並行実行時は、先行プロセスが適用済みの version を読み取った場合は
    スキップして成功として扱う。
    """
    if not isinstance(version, int):
        raise TypeError(f"version must be an int, got {type(version).__name__}")
    conn.execute("BEGIN IMMEDIATE")
    try:
        actual = get_schema_version(conn)
        if actual > len(MIGRATIONS):
            raise RuntimeError(
                f"schema version {actual} is newer than supported "
                f"(latest={len(MIGRATIONS)})"
            )
        if actual >= version:
            conn.commit()
            return
        if actual != version - 1:
            raise RuntimeError(
                f"schema version changed during migration: expected {version - 1}, "
                f"got {actual}"
            )
        MIGRATIONS[version - 1](conn)
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
