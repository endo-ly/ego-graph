"""SQLite schema bootstrap."""

import sqlite3


def initialize_schema(conn: sqlite3.Connection) -> None:
    """pipelines 管理テーブルを作成する。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS workflow_definitions (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            definition_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

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
        );

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
        );

        CREATE INDEX IF NOT EXISTS idx_workflow_runs_status_queued_at
            ON workflow_runs(status, queued_at);
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id
            ON workflow_runs(workflow_id, queued_at);

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
        );

        CREATE INDEX IF NOT EXISTS idx_step_runs_run_id_sequence
            ON step_runs(run_id, sequence_no, attempt_no);

        CREATE TABLE IF NOT EXISTS workflow_locks (
            lock_key TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            lease_owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS google_health_connections (
            connection_id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (
                status IN ('active', 'expired', 'revoked', 'error')
            ),
            scopes_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_error_message TEXT
        );

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
        );

        CREATE TABLE IF NOT EXISTS google_health_sync_cursors (
            connection_id TEXT NOT NULL,
            data_type TEXT NOT NULL,
            cursor TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (connection_id, data_type),
            FOREIGN KEY (connection_id)
              REFERENCES google_health_connections(connection_id)
              ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS google_health_oauth_states (
            state_hash TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    _migrate_google_health_sync_cursors(conn)
    conn.commit()


def _migrate_google_health_sync_cursors(conn: sqlite3.Connection) -> None:
    """既存のGoogle Health sync cursorへPhase 2列を追加する。"""
    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(google_health_sync_cursors)"
        ).fetchall()
    }
    additions = {
        "status": (
            "ALTER TABLE google_health_sync_cursors "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'success'"
        ),
        "range_start": (
            "ALTER TABLE google_health_sync_cursors ADD COLUMN range_start TEXT"
        ),
        "range_end": (
            "ALTER TABLE google_health_sync_cursors ADD COLUMN range_end TEXT"
        ),
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
    for name, statement in additions.items():
        if name not in columns:
            conn.execute(statement)
