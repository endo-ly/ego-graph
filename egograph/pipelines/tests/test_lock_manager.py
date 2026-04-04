from datetime import UTC, datetime, timedelta

from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.infrastructure.dispatching.lock_manager import WorkflowLockManager


def test_acquire_blocks_active_lock_and_releases(tmp_path):
    """active lease を保持している間は同じ lock_key を再取得できない。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    lock_manager = WorkflowLockManager(conn, lease_seconds=60)
    lease = lock_manager.acquire(lock_key="dummy_workflow", run_id="run-1")

    # Act & Assert
    try:
        lock_manager.acquire(lock_key="dummy_workflow", run_id="run-2")
    except Exception as exc:
        assert "active" in str(exc)
    else:
        raise AssertionError("active lock was re-acquired")

    lock_manager.release(lease)
    next_lease = lock_manager.acquire(lock_key="dummy_workflow", run_id="run-2")
    assert next_lease.run_id == "run-2"


def test_cleanup_stale_locks_removes_expired_lease(tmp_path):
    """期限切れ lease を startup reconcile で回収できる。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    conn.execute(
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
        """,
        (
            "dummy_workflow",
            "run-1",
            "owner",
            datetime.now(tz=UTC).isoformat(),
            datetime.now(tz=UTC).isoformat(),
            (datetime.now(tz=UTC) - timedelta(seconds=1)).isoformat(),
        ),
    )
    conn.commit()
    lock_manager = WorkflowLockManager(conn, lease_seconds=60)

    # Act
    deleted = lock_manager.cleanup_stale_locks()

    # Assert
    assert deleted == 1
    lease = lock_manager.acquire(lock_key="dummy_workflow", run_id="run-2")
    assert lease.run_id == "run-2"
