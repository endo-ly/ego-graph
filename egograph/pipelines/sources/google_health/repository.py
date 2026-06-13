"""Google Health 接続の永続化。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime

from pipelines.infrastructure.db._shared import (
    SQLiteRepository,
    dt_to_text,
    text_to_dt,
    utc_now,
)
from pipelines.sources.google_health.models import (
    ConnectionStatus,
    EncryptedOAuthToken,
    GoogleHealthConnection,
    GoogleHealthSyncCursor,
    OAuthToken,
    SyncStatus,
)

CONNECTION_ID = "google-health-primary"


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _required_datetime(value: str | None, field_name: str) -> datetime:
    parsed = text_to_dt(value)
    if parsed is None:
        raise ValueError(f"invalid_{field_name}: datetime is required")
    return parsed


def _map_connection(row: sqlite3.Row) -> GoogleHealthConnection:
    return GoogleHealthConnection(
        connection_id=row["connection_id"],
        status=ConnectionStatus(row["status"]),
        scopes=tuple(json.loads(row["scopes_json"])),
        created_at=_required_datetime(row["created_at"], "created_at"),
        updated_at=_required_datetime(row["updated_at"], "updated_at"),
        last_error_message=row["last_error_message"],
    )


def _map_token(row: sqlite3.Row) -> EncryptedOAuthToken:
    return EncryptedOAuthToken(
        connection_id=row["connection_id"],
        access_token_encrypted=row["access_token_encrypted"],
        refresh_token_encrypted=row["refresh_token_encrypted"],
        expires_at=_required_datetime(row["expires_at"], "expires_at"),
        token_type=row["token_type"],
        updated_at=_required_datetime(row["updated_at"], "updated_at"),
    )


def _map_sync_cursor(row: sqlite3.Row) -> GoogleHealthSyncCursor:
    return GoogleHealthSyncCursor(
        connection_id=row["connection_id"],
        data_type=row["data_type"],
        cursor=row["cursor"],
        status=SyncStatus(row["status"]),
        range_start=date.fromisoformat(row["range_start"])
        if row["range_start"]
        else None,
        range_end=date.fromisoformat(row["range_end"]) if row["range_end"] else None,
        last_run_id=row["last_run_id"],
        record_count=row["record_count"],
        last_error_message=row["last_error_message"],
        updated_at=_required_datetime(row["updated_at"], "updated_at"),
    )


class GoogleHealthRepository(SQLiteRepository):
    """Google Health connection、token、OAuth state を永続化する。"""

    def save_oauth_state(self, state: str, expires_at: datetime) -> None:
        """OAuth state のハッシュと期限を保存する。"""
        now = utc_now()
        with self._mutex, self._conn:
            self._conn.execute(
                "DELETE FROM google_health_oauth_states WHERE expires_at <= ?",
                (dt_to_text(now),),
            )
            self._conn.execute(
                """
                INSERT INTO google_health_oauth_states (
                    state_hash,
                    expires_at,
                    created_at
                )
                VALUES (?, ?, ?)
                """,
                (_state_hash(state), dt_to_text(expires_at), dt_to_text(now)),
            )

    def consume_oauth_state(self, state: str) -> bool:
        """未期限切れ state を一度だけ消費する。"""
        now_text = dt_to_text(utc_now())
        with self._mutex, self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM google_health_oauth_states
                WHERE state_hash = ? AND expires_at > ?
                """,
                (_state_hash(state), now_text),
            )
        return cursor.rowcount == 1

    def save_connection(
        self,
        *,
        token: OAuthToken,
        access_token_encrypted: bytes,
        refresh_token_encrypted: bytes,
    ) -> GoogleHealthConnection:
        """単一 connection と暗号化 token を保存または更新する。"""
        now = utc_now()
        with self._mutex, self._conn:
            self._conn.execute(
                """
                INSERT INTO google_health_connections (
                    connection_id,
                    status,
                    scopes_json,
                    created_at,
                    updated_at,
                    last_error_message
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(connection_id) DO UPDATE SET
                    status = excluded.status,
                    scopes_json = excluded.scopes_json,
                    updated_at = excluded.updated_at,
                    last_error_message = NULL
                """,
                (
                    CONNECTION_ID,
                    ConnectionStatus.ACTIVE.value,
                    json.dumps(token.scopes, sort_keys=True),
                    dt_to_text(now),
                    dt_to_text(now),
                ),
            )
            self._conn.execute(
                """
                INSERT INTO google_health_oauth_tokens (
                    connection_id,
                    access_token_encrypted,
                    refresh_token_encrypted,
                    expires_at,
                    token_type,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    access_token_encrypted = excluded.access_token_encrypted,
                    refresh_token_encrypted = excluded.refresh_token_encrypted,
                    expires_at = excluded.expires_at,
                    token_type = excluded.token_type,
                    updated_at = excluded.updated_at
                """,
                (
                    CONNECTION_ID,
                    access_token_encrypted,
                    refresh_token_encrypted,
                    dt_to_text(token.expires_at),
                    token.token_type,
                    dt_to_text(now),
                ),
            )
        connection = self.get_connection()
        if connection is None:  # pragma: no cover
            raise RuntimeError("google_health_connection_fetch_failed")
        return connection

    def get_connection(self) -> GoogleHealthConnection | None:
        """現在の connection を取得する。"""
        with self._mutex:
            row = self._conn.execute(
                """
                SELECT *
                FROM google_health_connections
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return _map_connection(row) if row else None

    def get_encrypted_token(
        self,
        connection_id: str,
    ) -> EncryptedOAuthToken | None:
        """暗号化 token を取得する。"""
        with self._mutex:
            row = self._conn.execute(
                """
                SELECT *
                FROM google_health_oauth_tokens
                WHERE connection_id = ?
                """,
                (connection_id,),
            ).fetchone()
        return _map_token(row) if row else None

    def update_token(
        self,
        connection_id: str,
        *,
        access_token_encrypted: bytes,
        refresh_token_encrypted: bytes,
        expires_at: datetime,
        token_type: str,
    ) -> None:
        """refresh 後の token を更新する。"""
        now = utc_now()
        with self._mutex, self._conn:
            self._conn.execute(
                """
                UPDATE google_health_oauth_tokens
                SET access_token_encrypted = ?,
                    refresh_token_encrypted = ?,
                    expires_at = ?,
                    token_type = ?,
                    updated_at = ?
                WHERE connection_id = ?
                """,
                (
                    access_token_encrypted,
                    refresh_token_encrypted,
                    dt_to_text(expires_at),
                    token_type,
                    dt_to_text(now),
                    connection_id,
                ),
            )
            self._conn.execute(
                """
                UPDATE google_health_connections
                SET status = ?,
                    updated_at = ?,
                    last_error_message = NULL
                WHERE connection_id = ?
                """,
                (
                    ConnectionStatus.ACTIVE.value,
                    dt_to_text(now),
                    connection_id,
                ),
            )

    def update_connection_status(
        self,
        connection_id: str,
        status: ConnectionStatus,
        error_message: str | None = None,
    ) -> GoogleHealthConnection:
        """connection status を更新する。"""
        with self._mutex, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE google_health_connections
                SET status = ?,
                    updated_at = ?,
                    last_error_message = ?
                WHERE connection_id = ?
                """,
                (
                    status.value,
                    dt_to_text(utc_now()),
                    error_message,
                    connection_id,
                ),
            )
        if cursor.rowcount == 0:
            raise ValueError("google_health_connection_not_found")
        connection = self.get_connection()
        if connection is None:  # pragma: no cover
            raise RuntimeError("google_health_connection_fetch_failed")
        return connection

    def save_sync_result(
        self,
        *,
        connection_id: str,
        data_type: str,
        status: SyncStatus,
        range_start: date,
        range_end: date,
        run_id: str,
        record_count: int = 0,
        cursor: str | None = None,
        error_message: str | None = None,
    ) -> GoogleHealthSyncCursor:
        """data type単位の最終同期結果を保存する。"""
        with self._mutex, self._conn:
            self._conn.execute(
                """
                INSERT INTO google_health_sync_cursors (
                    connection_id,
                    data_type,
                    cursor,
                    status,
                    range_start,
                    range_end,
                    last_run_id,
                    record_count,
                    last_error_message,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id, data_type) DO UPDATE SET
                    cursor = excluded.cursor,
                    status = excluded.status,
                    range_start = excluded.range_start,
                    range_end = excluded.range_end,
                    last_run_id = excluded.last_run_id,
                    record_count = excluded.record_count,
                    last_error_message = excluded.last_error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    connection_id,
                    data_type,
                    cursor,
                    status.value,
                    range_start.isoformat(),
                    range_end.isoformat(),
                    run_id,
                    record_count,
                    error_message,
                    dt_to_text(utc_now()),
                ),
            )
        result = self.get_sync_cursor(connection_id, data_type)
        if result is None:  # pragma: no cover
            raise RuntimeError("google_health_sync_cursor_fetch_failed")
        return result

    def get_sync_cursor(
        self,
        connection_id: str,
        data_type: str,
    ) -> GoogleHealthSyncCursor | None:
        """data typeの最終同期結果を取得する。"""
        with self._mutex:
            row = self._conn.execute(
                """
                SELECT *
                FROM google_health_sync_cursors
                WHERE connection_id = ? AND data_type = ?
                """,
                (connection_id, data_type),
            ).fetchone()
        return _map_sync_cursor(row) if row else None

    def list_sync_results_for_run(
        self,
        connection_id: str,
        run_id: str,
    ) -> list[GoogleHealthSyncCursor]:
        """指定runで更新されたdata type別同期結果を返す。"""
        with self._mutex:
            rows = self._conn.execute(
                """
                SELECT *
                FROM google_health_sync_cursors
                WHERE connection_id = ? AND last_run_id = ?
                ORDER BY data_type
                """,
                (connection_id, run_id),
            ).fetchall()
        return [_map_sync_cursor(row) for row in rows]

    def delete_connection(self, connection_id: str) -> bool:
        """connection と関連 token/cursor を削除する。"""
        with self._mutex, self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM google_health_connections
                WHERE connection_id = ?
                """,
                (connection_id,),
            )
        return cursor.rowcount == 1
