"""SQLite-backed workflow lock manager."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pipelines.domain.errors import WorkflowLockUnavailableError


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class WorkflowLease:
    """workflow lock の lease 情報。"""

    lock_key: str
    run_id: str
    lease_owner: str


class WorkflowLockManager:
    """lease + heartbeat 方式で workflow_locks を管理する。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        lease_seconds: int,
        *,
        mutex: threading.RLock | None = None,
    ) -> None:
        self._conn = conn
        self._lease_seconds = lease_seconds
        self._lease_owner = f"pipelines-{uuid.uuid4()}"
        self._mutex = mutex or threading.RLock()

    @property
    def lease_owner(self) -> str:
        """このプロセスの lease owner ID。"""
        return self._lease_owner

    def acquire(self, *, lock_key: str, run_id: str) -> WorkflowLease:
        """stale lock を回収しながら lock を取得する。"""
        now = _utc_now()
        expires_at = now + timedelta(seconds=self._lease_seconds)
        with self._mutex, self._conn:
            row = self._conn.execute(
                """
                SELECT lock_key, lease_expires_at
                FROM workflow_locks
                WHERE lock_key = ?
                """,
                (lock_key,),
            ).fetchone()
            if (
                row is not None
                and datetime.fromisoformat(row["lease_expires_at"]) >= now
            ):
                raise WorkflowLockUnavailableError(
                    f"workflow lock is active: {lock_key}"
                )
            self._conn.execute(
                """
                INSERT INTO workflow_locks (
                    lock_key,
                    run_id,
                    lease_owner,
                    acquired_at,
                    heartbeat_at,
                    lease_expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(lock_key) DO UPDATE SET
                    run_id = excluded.run_id,
                    lease_owner = excluded.lease_owner,
                    acquired_at = excluded.acquired_at,
                    heartbeat_at = excluded.heartbeat_at,
                    lease_expires_at = excluded.lease_expires_at
                """,
                (
                    lock_key,
                    run_id,
                    self._lease_owner,
                    now.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return WorkflowLease(
            lock_key=lock_key,
            run_id=run_id,
            lease_owner=self._lease_owner,
        )

    def heartbeat(self, lease: WorkflowLease) -> None:
        """lease の期限を延長する。"""
        now = _utc_now()
        expires_at = now + timedelta(seconds=self._lease_seconds)
        with self._mutex, self._conn:
            self._conn.execute(
                """
                UPDATE workflow_locks
                SET heartbeat_at = ?,
                    lease_expires_at = ?
                WHERE lock_key = ?
                  AND run_id = ?
                  AND lease_owner = ?
                """,
                (
                    now.isoformat(),
                    expires_at.isoformat(),
                    lease.lock_key,
                    lease.run_id,
                    lease.lease_owner,
                ),
            )

    def release(self, lease: WorkflowLease) -> None:
        """保持中 lease を解放する。"""
        with self._mutex, self._conn:
            self._conn.execute(
                """
                DELETE FROM workflow_locks
                WHERE lock_key = ?
                  AND run_id = ?
                  AND lease_owner = ?
                """,
                (
                    lease.lock_key,
                    lease.run_id,
                    lease.lease_owner,
                ),
            )

    def cleanup_stale_locks(self) -> int:
        """期限切れ lock を削除する。"""
        now = _utc_now().isoformat()
        with self._mutex, self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM workflow_locks
                WHERE lease_expires_at < ?
                """,
                (now,),
            )
            return cursor.rowcount
