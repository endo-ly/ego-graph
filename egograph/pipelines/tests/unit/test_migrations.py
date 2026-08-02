"""SQLite migration runner のテスト。"""

import sqlite3

import pytest
from pipelines.infrastructure.db import migrations
from pipelines.infrastructure.db.schema import initialize_schema

_BASE_TABLES = (
    "workflow_definitions",
    "workflow_schedules",
    "workflow_runs",
    "step_runs",
    "workflow_locks",
    "google_health_connections",
    "google_health_oauth_tokens",
    "google_health_sync_cursors",
    "google_health_oauth_states",
)

_CURSOR_PHASE2_COLUMNS = (
    "status",
    "range_start",
    "range_end",
    "last_run_id",
    "record_count",
    "last_error_message",
)


@pytest.fixture
def conn():
    """in-memory SQLite 接続。"""
    connection = sqlite3.connect(":memory:")
    yield connection
    connection.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _cursor_columns(conn: sqlite3.Connection) -> set[str]:
    return {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(google_health_sync_cursors)"
        ).fetchall()
    }


def test_fresh_database_reaches_latest_schema_version(conn):
    """空DBは基準schemaと全migrationが適用され最新versionになる。"""
    # Act
    initialize_schema(conn)

    # Assert
    assert migrations.get_schema_version(conn) == len(migrations.MIGRATIONS)
    assert set(_BASE_TABLES) <= _table_names(conn)
    assert set(_CURSOR_PHASE2_COLUMNS) <= _cursor_columns(conn)


def test_initialize_schema_is_idempotent(conn):
    """migration を複数回実行しても schema が壊れない。"""
    # Arrange
    initialize_schema(conn)
    before_columns = _cursor_columns(conn)
    before_version = migrations.get_schema_version(conn)

    # Act
    initialize_schema(conn)

    # Assert
    assert migrations.get_schema_version(conn) == before_version
    assert _cursor_columns(conn) == before_columns


def test_phase1_cursors_database_upgrades_without_duplicate_columns(conn):
    """Phase 1 の既存DBは不足列だけを補って最新versionへ昇格する。"""
    # Arrange
    conn.executescript(
        """
        CREATE TABLE google_health_connections (
            connection_id TEXT PRIMARY KEY
        );
        CREATE TABLE google_health_sync_cursors (
            connection_id TEXT NOT NULL,
            data_type TEXT NOT NULL,
            cursor TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (connection_id, data_type)
        );
        """
    )

    # Act
    initialize_schema(conn)

    # Assert
    assert migrations.get_schema_version(conn) == len(migrations.MIGRATIONS)
    assert set(_CURSOR_PHASE2_COLUMNS) <= _cursor_columns(conn)
    assert set(_BASE_TABLES) <= _table_names(conn)


def test_phase2_cursors_database_is_not_duplicated(conn):
    """Phase 2 適用済みの既存DBは列を追加せずそのまま維持される。"""
    # Arrange
    conn.executescript(
        """
        CREATE TABLE google_health_connections (
            connection_id TEXT PRIMARY KEY
        );
        CREATE TABLE google_health_sync_cursors (
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
            PRIMARY KEY (connection_id, data_type)
        );
        """
    )

    # Act
    initialize_schema(conn)

    # Assert
    assert migrations.get_schema_version(conn) == len(migrations.MIGRATIONS)
    assert _cursor_columns(conn) == {
        "connection_id",
        "data_type",
        "cursor",
        "updated_at",
        *_CURSOR_PHASE2_COLUMNS,
    }


def test_migration_failure_rolls_back_schema_and_version(conn, monkeypatch):
    """途中失敗時はrollbackされ user_version も進まない。"""
    # Arrange
    original_count = len(migrations.MIGRATIONS)

    def broken_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE rollback_probe (id INTEGER)")
        raise RuntimeError("migration failure")

    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        (*migrations.MIGRATIONS, broken_migration),
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="migration failure"):
        migrations.run_migrations(conn)

    # Assert
    assert migrations.get_schema_version(conn) == original_count
    assert "rollback_probe" not in _table_names(conn)


def test_run_migrations_rejects_newer_schema_version(conn):
    """対応外の新しいschema versionのDBは適用せずエラーにする。"""
    # Arrange
    conn.execute("PRAGMA user_version = 99")

    # Act / Assert
    with pytest.raises(RuntimeError, match="newer than supported"):
        migrations.run_migrations(conn)

    assert migrations.get_schema_version(conn) == 99


def test_apply_migration_skips_versions_applied_by_other_process(conn):
    """並行実行で先行プロセスが適用済みの version はスキップして成功する。"""
    # Arrange: 後続プロセスが current=0 を読んだ後に先行プロセスが
    # version 1 を適用した状況を再現する
    conn.execute("PRAGMA user_version = 1")

    # Act
    migrations._apply_migration(conn, 1)

    # Assert
    assert migrations.get_schema_version(conn) == 1
    assert not _table_names(conn)
