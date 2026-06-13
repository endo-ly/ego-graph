"""Google Health connection repository のテスト。"""

from datetime import UTC, date, datetime, timedelta

import pytest
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.sources.google_health.models import (
    ConnectionStatus,
    OAuthToken,
    SyncStatus,
)
from pipelines.sources.google_health.repository import GoogleHealthRepository


@pytest.fixture
def repository(tmp_path):
    """初期化済み repository を返す。"""
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    return GoogleHealthRepository(conn)


def test_oauth_state_is_single_use(repository):
    """OAuth state は一度だけ利用できる。"""
    # Arrange
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=10)
    repository.save_oauth_state("state", expires_at)

    # Act
    first_result = repository.consume_oauth_state("state")
    second_result = repository.consume_oauth_state("state")

    # Assert
    assert first_result is True
    assert second_result is False


def test_save_connection_and_delete_cascades_token(repository):
    """connection 削除時に token も削除される。"""
    # Arrange
    token = OAuthToken(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        token_type="Bearer",
        scopes=("scope-a",),
    )
    connection = repository.save_connection(
        token=token,
        access_token_encrypted=b"encrypted-access",
        refresh_token_encrypted=b"encrypted-refresh",
    )

    # Act
    repository.delete_connection(connection.connection_id)

    # Assert
    assert repository.get_connection() is None
    assert repository.get_encrypted_token(connection.connection_id) is None


def test_reauthorization_updates_single_connection(repository):
    """再認証は同じ connection を更新する。"""
    # Arrange
    original = repository.save_connection(
        token=OAuthToken(
            access_token="old-access-token",
            refresh_token="old-refresh-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            token_type="Bearer",
            scopes=("scope-a",),
        ),
        access_token_encrypted=b"old-encrypted-access",
        refresh_token_encrypted=b"old-encrypted-refresh",
    )

    # Act
    updated = repository.save_connection(
        token=OAuthToken(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            token_type="Bearer",
            scopes=("scope-a", "scope-b"),
        ),
        access_token_encrypted=b"new-encrypted-access",
        refresh_token_encrypted=b"new-encrypted-refresh",
    )
    encrypted = repository.get_encrypted_token(updated.connection_id)

    # Assert
    assert updated.connection_id == original.connection_id
    assert updated.scopes == ("scope-a", "scope-b")
    assert encrypted is not None
    assert encrypted.access_token_encrypted == b"new-encrypted-access"
    assert encrypted.refresh_token_encrypted == b"new-encrypted-refresh"


def test_update_status_preserves_supported_connection_state(repository):
    """connection status とエラーを更新できる。"""
    # Arrange
    token = OAuthToken(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        token_type="Bearer",
        scopes=("scope-a",),
    )
    connection = repository.save_connection(
        token=token,
        access_token_encrypted=b"encrypted-access",
        refresh_token_encrypted=b"encrypted-refresh",
    )

    # Act
    updated = repository.update_connection_status(
        connection.connection_id,
        ConnectionStatus.REVOKED,
        "refresh token revoked",
    )

    # Assert
    assert updated.status is ConnectionStatus.REVOKED
    assert updated.last_error_message == "refresh token revoked"


def test_save_sync_result_upserts_data_type_state(repository):
    """data type単位の同期結果をSQLiteへupsertできる。"""
    # Arrange
    token = OAuthToken(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        token_type="Bearer",
        scopes=("scope-a",),
    )
    connection = repository.save_connection(
        token=token,
        access_token_encrypted=b"encrypted-access",
        refresh_token_encrypted=b"encrypted-refresh",
    )

    # Act
    repository.save_sync_result(
        connection_id=connection.connection_id,
        data_type="steps",
        status=SyncStatus.FAILED,
        range_start=date(2026, 6, 1),
        range_end=date(2026, 6, 3),
        run_id="run-1",
        error_message="temporary failure",
    )
    updated = repository.save_sync_result(
        connection_id=connection.connection_id,
        data_type="steps",
        status=SyncStatus.SUCCESS,
        range_start=date(2026, 6, 1),
        range_end=date(2026, 6, 3),
        run_id="run-2",
        record_count=42,
    )
    run_results = repository.list_sync_results_for_run(
        connection.connection_id,
        "run-2",
    )

    # Assert
    assert updated.status is SyncStatus.SUCCESS
    assert updated.range_start == date(2026, 6, 1)
    assert updated.range_end == date(2026, 6, 3)
    assert updated.last_run_id == "run-2"
    assert updated.record_count == 42
    assert updated.last_error_message is None
    assert run_results == [updated]
