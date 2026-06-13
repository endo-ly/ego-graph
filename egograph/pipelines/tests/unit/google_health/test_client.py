"""Google Health API client のテスト。"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests
from cryptography.fernet import Fernet
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.sources.google_health.client import (
    GoogleHealthAPIClient,
    GoogleHealthAuthenticationError,
    GoogleHealthRateLimitError,
)
from pipelines.sources.google_health.models import OAuthToken
from pipelines.sources.google_health.repository import GoogleHealthRepository
from pipelines.sources.google_health.token_cipher import TokenCipher


class FakeResponse:
    """requests.Response の最小代替。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "response"

    def json(self):
        return self._payload


class FakeSession:
    """順番に response または例外を返す。"""

    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, *, data, timeout):
        return self.request("POST", url, data=data, timeout=timeout)


def _repository_with_token(tmp_path, *, expired=False):
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    repository = GoogleHealthRepository(conn)
    cipher = TokenCipher(Fernet.generate_key().decode())
    token = OAuthToken(
        access_token="old-access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(tz=UTC)
        + (timedelta(seconds=-1) if expired else timedelta(hours=1)),
        token_type="Bearer",
        scopes=("scope-a",),
    )
    connection = repository.save_connection(
        token=token,
        access_token_encrypted=cipher.encrypt(token.access_token),
        refresh_token_encrypted=cipher.encrypt(token.refresh_token),
    )
    return repository, cipher, connection


def test_list_data_points_uses_bearer_token(tmp_path):
    """data point list は保存済み access token を利用する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession([FakeResponse({"dataPoints": []})])
    client = GoogleHealthAPIClient(repository, cipher, session=session)

    # Act
    result = client.list_data_points(connection.connection_id, "steps")

    # Assert
    assert result == {"dataPoints": []}
    assert session.calls[0][2]["headers"]["Authorization"] == (
        "Bearer old-access-token"
    )


def test_reconcile_data_points_sends_filter_and_page_token(tmp_path):
    """reconcileは期間filterとpagination tokenを送信する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession([FakeResponse({"dataPoints": []})])
    client = GoogleHealthAPIClient(repository, cipher, session=session)

    # Act
    client.reconcile_data_points(
        connection.connection_id,
        "steps",
        filter_expression='steps.interval.start_time >= "2026-06-01T00:00:00Z"',
        page_size=10000,
        page_token="next-token",
    )

    # Assert
    params = session.calls[0][2]["params"]
    assert params["filter"] == 'steps.interval.start_time >= "2026-06-01T00:00:00Z"'
    assert params["pageToken"] == "next-token"
    assert params["pageSize"] == 10000
    assert params["dataSourceFamily"].endswith("/google-wearables")


def test_daily_rollup_sends_closed_open_civil_range(tmp_path):
    """daily rollupはcivil dateのclosed-open範囲を送信する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession([FakeResponse({"rollupDataPoints": []})])
    client = GoogleHealthAPIClient(repository, cipher, session=session)

    # Act
    client.daily_rollup(
        connection.connection_id,
        "steps",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 3),
    )

    # Assert
    body = session.calls[0][2]["json"]
    assert body["range"]["start"]["date"] == {
        "year": 2026,
        "month": 6,
        "day": 1,
    }
    assert body["range"]["end"]["date"]["day"] == 3


def test_rollup_sends_physical_range_and_window(tmp_path):
    """physical rollupはRFC3339範囲とwindow sizeを送信する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession([FakeResponse({"rollupDataPoints": []})])
    client = GoogleHealthAPIClient(repository, cipher, session=session)

    # Act
    client.rollup(
        connection.connection_id,
        "calories-in-heart-rate-zone",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 3),
        window_size_seconds=300,
    )

    # Assert
    body = session.calls[0][2]["json"]
    assert body["range"] == {
        "startTime": "2026-06-01T00:00:00Z",
        "endTime": "2026-06-03T00:00:00Z",
    }
    assert body["windowSize"] == "300s"


def test_rollup_uses_configured_timezone_boundary(tmp_path):
    """physical rollupは設定TZのローカル日付境界をUTCで送信する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession([FakeResponse({"rollupDataPoints": []})])
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        session=session,
        timezone=ZoneInfo("Asia/Tokyo"),
    )

    # Act
    client.rollup(
        connection.connection_id,
        "heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        window_size_seconds=300,
    )

    # Assert
    assert session.calls[0][2]["json"]["range"] == {
        "startTime": "2026-05-31T15:00:00Z",
        "endTime": "2026-06-01T15:00:00Z",
    }


def test_expired_access_token_is_refreshed_before_request(tmp_path):
    """期限切れ access token は API 呼び出し前に refresh する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(
        tmp_path,
        expired=True,
    )
    session = FakeSession(
        [
            FakeResponse(
                {
                    "access_token": "new-access-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }
            ),
            FakeResponse({"dataPoints": []}),
        ]
    )
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act
    client.list_data_points(connection.connection_id, "steps")

    # Assert
    assert session.calls[1][2]["headers"]["Authorization"] == (
        "Bearer new-access-token"
    )


def test_unauthorized_response_refreshes_and_retries_request(tmp_path):
    """401 は access token を refresh して一度だけ再送する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession(
        [
            FakeResponse({}, status_code=401),
            FakeResponse(
                {
                    "access_token": "new-access-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }
            ),
            FakeResponse({"dataPoints": []}),
        ]
    )
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act
    result = client.list_data_points(connection.connection_id, "steps")

    # Assert
    assert result == {"dataPoints": []}
    assert session.calls[2][2]["headers"]["Authorization"] == (
        "Bearer new-access-token"
    )


def test_unauthorized_refresh_does_not_consume_only_request_attempt(tmp_path):
    """401後のrefresh再送はmax_attemptsが1でも実行できる。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession(
        [
            FakeResponse({}, status_code=401),
            FakeResponse(
                {
                    "access_token": "new-access-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }
            ),
            FakeResponse({"dataPoints": []}),
        ]
    )
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
        max_attempts=1,
    )

    # Act
    result = client.list_data_points(connection.connection_id, "steps")

    # Assert
    assert result == {"dataPoints": []}
    assert session.calls[2][2]["headers"]["Authorization"] == (
        "Bearer new-access-token"
    )


def test_network_error_and_server_error_are_retried(tmp_path):
    """network error と 5xx は retry する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession(
        [
            requests.ConnectionError("offline"),
            FakeResponse({}, status_code=503),
            FakeResponse({"dataPoints": []}),
        ]
    )
    sleeps = []
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        session=session,
        sleep=sleeps.append,
    )

    # Act
    result = client.list_data_points(connection.connection_id, "steps")

    # Assert
    assert result == {"dataPoints": []}
    assert len(session.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_rate_limit_error_is_classified_after_retries(tmp_path):
    """429 は retry 後に rate limit error として分類する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession([FakeResponse({}, status_code=429)] * 3)
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        session=session,
        sleep=lambda _: None,
    )

    # Act & Assert
    try:
        client.list_data_points(connection.connection_id, "steps")
    except GoogleHealthRateLimitError:
        pass
    else:
        raise AssertionError("GoogleHealthRateLimitError was not raised")


def test_refresh_rejection_marks_connection_revoked(tmp_path):
    """refresh token 拒否時は connection を revoked にする。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(
        tmp_path,
        expired=True,
    )
    session = FakeSession([FakeResponse({}, status_code=400)])
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError):
        client.list_data_points(connection.connection_id, "steps")

    updated = repository.get_connection()
    assert updated is not None
    assert updated.status.value == "revoked"
