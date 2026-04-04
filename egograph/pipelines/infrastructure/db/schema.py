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
        """
    )
    conn.commit()
