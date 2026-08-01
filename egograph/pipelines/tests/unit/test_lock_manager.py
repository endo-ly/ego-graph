from datetime import UTC, datetime, timedelta

from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.infrastructure.dispatching.lock_manager import (
    WorkflowLease,
    WorkflowLockManager,
)


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


def test_heartbeat_returns_true_for_current_lease(tmp_path):
    """現在のrunとownerが保持するleaseだけheartbeatに成功する。"""
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    lock_manager = WorkflowLockManager(conn, lease_seconds=60)
    lease = lock_manager.acquire(lock_key="dummy_workflow", run_id="run-1")

    # Act
    heartbeat_succeeded = lock_manager.heartbeat(lease)

    # Assert
    assert heartbeat_succeeded is True


def test_heartbeat_returns_false_when_lock_is_missing(tmp_path):
    """対象lockが削除済みならheartbeatに失敗する。"""
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    lock_manager = WorkflowLockManager(conn, lease_seconds=60)
    lease = lock_manager.acquire(lock_key="dummy_workflow", run_id="run-1")
    conn.execute("DELETE FROM workflow_locks WHERE lock_key = ?", (lease.lock_key,))
    conn.commit()

    # Act
    heartbeat_succeeded = lock_manager.heartbeat(lease)

    # Assert
    assert heartbeat_succeeded is False


def test_heartbeat_returns_false_for_different_run_id(tmp_path):
    """run_idが異なるheartbeatは失敗する。"""
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    lock_manager = WorkflowLockManager(conn, lease_seconds=60)
    lease = lock_manager.acquire(lock_key="dummy_workflow", run_id="run-1")
    wrong_run_lease = WorkflowLease(
        lock_key=lease.lock_key,
        run_id="run-2",
        lease_owner=lease.lease_owner,
    )

    # Act
    heartbeat_succeeded = lock_manager.heartbeat(wrong_run_lease)

    # Assert
    assert heartbeat_succeeded is False


def test_heartbeat_returns_false_for_different_lease_owner(tmp_path):
    """lease_ownerが異なるheartbeatは失敗する。"""
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    lock_manager = WorkflowLockManager(conn, lease_seconds=60)
    lease = lock_manager.acquire(lock_key="dummy_workflow", run_id="run-1")
    wrong_owner_lease = WorkflowLease(
        lock_key=lease.lock_key,
        run_id=lease.run_id,
        lease_owner="other-owner",
    )

    # Act
    heartbeat_succeeded = lock_manager.heartbeat(wrong_owner_lease)

    # Assert
    assert heartbeat_succeeded is False
