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
    GoogleHealthClientError,
    GoogleHealthRateLimitError,
)
from pipelines.sources.google_health.models import ConnectionStatus, OAuthToken
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
    assert "dataSourceFamily" not in params


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
    assert "dataSourceFamily" not in body


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
    assert "dataSourceFamily" not in body


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


def test_client_error_preserves_safe_google_diagnostics(tmp_path):
    """Google APIの4xx本文から構造化された診断情報を保持する。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path)
    session = FakeSession(
        [
            FakeResponse(
                {
                    "error": {
                        "code": 400,
                        "status": "INVALID_ARGUMENT",
                        "message": "Invalid filter for exercise",
                        "details": [
                            {
                                "reason": "INVALID_FILTER",
                                "metadata": {"token": "must-not-be-stored"},
                            }
                        ],
                    }
                },
                status_code=400,
            )
        ]
    )
    client = GoogleHealthAPIClient(repository, cipher, session=session)

    # Act & Assert
    with pytest.raises(GoogleHealthClientError) as exc_info:
        client.list_data_points(connection.connection_id, "exercise")

    summary = str(exc_info.value)
    assert "google_health_request_failed: status=400" in summary
    assert "method=GET" in summary
    assert "dataTypes/exercise/dataPoints" in summary
    assert "api_status=INVALID_ARGUMENT" in summary
    assert "reason=INVALID_FILTER" in summary
    assert "message=Invalid filter for exercise" in summary
    assert "must-not-be-stored" not in summary


def test_refresh_rejection_marks_connection_revoked(tmp_path):
    """refresh token 拒否時は connection を revoked にする。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(
        tmp_path,
        expired=True,
    )
    session = FakeSession(
        [
            FakeResponse(
                {"error": "invalid_grant"},
                status_code=400,
            )
        ]
    )
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


def test_refresh_invalid_grant_persists_safe_diagnostics(tmp_path):
    """refresh 400 invalid_grant は安全な診断を保存し connection を revoked にする。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path, expired=True)
    session = FakeSession(
        [
            FakeResponse(
                {
                    "error": "invalid_grant",
                    "error_description": "Token has been expired or revoked.",
                },
                status_code=400,
            )
        ]
    )
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError) as exc_info:
        client.list_data_points(connection.connection_id, "steps")

    summary = str(exc_info.value)
    assert "oauth_refresh_failed" in summary
    assert "status=400" in summary
    assert "error=invalid_grant" in summary
    # provider 由来の error_description は例外メッセージに保存しない
    assert "Token has been expired or revoked" not in summary
    # 秘密情報が例外メッセージに混入しない
    assert "refresh-token" not in summary
    assert "client-secret" not in summary

    updated = repository.get_connection()
    assert updated is not None
    assert updated.status == ConnectionStatus.REVOKED
    assert updated.last_error_message is not None
    assert "oauth_refresh_failed" in updated.last_error_message
    assert "error=invalid_grant" in updated.last_error_message
    # provider 由来の error_description は DB の last_error_message にも保存しない
    assert "Token has been expired or revoked" not in updated.last_error_message
    # 秘密情報が DB の last_error_message に混入しない
    assert "refresh-token" not in updated.last_error_message


def test_refresh_error_description_with_token_like_text_is_not_persisted(tmp_path):
    """error_description に token 的文字列が含まれていても保存・伝播しない。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path, expired=True)
    sensitive_description = "refresh_token=refresh-token; code=authz-code-123"
    session = FakeSession(
        [
            FakeResponse(
                {
                    "error": "invalid_grant",
                    "error_description": sensitive_description,
                },
                status_code=400,
            )
        ]
    )
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError) as exc_info:
        client.list_data_points(connection.connection_id, "steps")

    summary = str(exc_info.value)
    assert "error=invalid_grant" in summary
    # error_description に含まれる token 的文字列は例外メッセージに漏れない
    assert "refresh-token" not in summary
    assert "authz-code-123" not in summary
    assert sensitive_description not in summary

    updated = repository.get_connection()
    assert updated is not None
    assert updated.last_error_message is not None
    # DB の last_error_message にも token 的文字列は漏れない
    assert "refresh-token" not in updated.last_error_message
    assert "authz-code-123" not in updated.last_error_message
    assert sensitive_description not in updated.last_error_message


def test_refresh_token_like_error_value_is_not_persisted(tmp_path):
    """許可リスト外の error / error_subtype 値は保存・伝播しない。

    provider が ``error`` / ``error_subtype`` に許可リスト外の文字列
    (token / code / 自由文など) を送ってきた場合、それを例外メッセージや
    ``last_error_message`` に保存しないことを保証する。
    """
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path, expired=True)
    # "=" / ";" / 空白を含む自由文 (許可リスト外)
    malicious_error = "refresh_token=secret-refresh-token; code=authz-code-123"
    # 許可リスト外の長い token 的文字列
    malicious_error_subtype = "ya29." + "a" * 200
    session = FakeSession(
        [
            FakeResponse(
                {
                    "error": malicious_error,
                    "error_subtype": malicious_error_subtype,
                },
                status_code=400,
            )
        ]
    )
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError) as exc_info:
        client.list_data_points(connection.connection_id, "steps")

    summary = str(exc_info.value)
    assert "oauth_refresh_failed" in summary
    assert "status=400" in summary
    # 許可リスト外の値は要約から除外されるため field 名自体登場しない
    assert "error=" not in summary
    assert "error_subtype=" not in summary
    # token 的文字列は例外メッセージに漏れない
    assert malicious_error not in summary
    assert malicious_error_subtype not in summary
    assert "secret-refresh-token" not in summary
    assert "authz-code-123" not in summary

    updated = repository.get_connection()
    assert updated is not None
    # 分類不能なので 4xx 扱いで ERROR になる
    assert updated.status == ConnectionStatus.ERROR
    assert updated.last_error_message is not None
    assert "oauth_refresh_failed" in updated.last_error_message
    assert "status=400" in updated.last_error_message
    # token 的文字列は DB の last_error_message にも漏れない
    assert "error=" not in updated.last_error_message
    assert "error_subtype=" not in updated.last_error_message
    assert malicious_error not in updated.last_error_message
    assert malicious_error_subtype not in updated.last_error_message
    assert "secret-refresh-token" not in updated.last_error_message
    assert "authz-code-123" not in updated.last_error_message


def test_refresh_identifier_shaped_non_allowlisted_value_is_not_persisted(tmp_path):
    """許可リスト外の identifier 形状値 (token/code 類似) は保存・伝播しない。

    ``error`` / ``error_subtype`` が OAuth 仕様の identifier 形状
    (ASCII letter/digit と記号のみの短い文字列) を満たしていても、明示的
    許可リストに含まれなければ保存対象から除外する。短い authorization
    code や token の断片は identifier 形状になり得るため、形状ではなく
    許可リストで制限する。
    """
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path, expired=True)
    # identifier 形状だが許可リスト外の token/code 的文字列
    token_like_error = "authz-code-123"
    token_like_subtype = "ya29-short-token"
    session = FakeSession(
        [
            FakeResponse(
                {
                    "error": token_like_error,
                    "error_subtype": token_like_subtype,
                },
                status_code=400,
            )
        ]
    )
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError) as exc_info:
        client.list_data_points(connection.connection_id, "steps")

    summary = str(exc_info.value)
    assert "oauth_refresh_failed" in summary
    assert "status=400" in summary
    # 許可リスト外の値は要約から除外されるため field 名自体登場しない
    assert "error=" not in summary
    assert "error_subtype=" not in summary
    # token/code 的文字列は例外メッセージに漏れない
    assert token_like_error not in summary
    assert token_like_subtype not in summary

    updated = repository.get_connection()
    assert updated is not None
    # 許可リスト外なので未分類 4xx 扱いで ERROR になる
    assert updated.status == ConnectionStatus.ERROR
    assert updated.last_error_message is not None
    assert "oauth_refresh_failed" in updated.last_error_message
    assert "status=400" in updated.last_error_message
    # token/code 的文字列は DB の last_error_message にも漏れない
    assert "error=" not in updated.last_error_message
    assert "error_subtype=" not in updated.last_error_message
    assert token_like_error not in updated.last_error_message
    assert token_like_subtype not in updated.last_error_message


def test_refresh_invalid_client_marks_error(tmp_path):
    """refresh 401 invalid_client は connection を error にする。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path, expired=True)
    session = FakeSession([FakeResponse({"error": "invalid_client"}, status_code=401)])
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError) as exc_info:
        client.list_data_points(connection.connection_id, "steps")

    assert "error=invalid_client" in str(exc_info.value)
    updated = repository.get_connection()
    assert updated is not None
    assert updated.status == ConnectionStatus.ERROR


def test_refresh_server_error_keeps_connection_active(tmp_path):
    """refresh 5xx は connection status を更新せず安全な診断で例外を投げる。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path, expired=True)
    session = FakeSession([FakeResponse({}, status_code=500)] * 3)
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
        sleep=lambda _: None,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError) as exc_info:
        client.list_data_points(connection.connection_id, "steps")

    assert "oauth_refresh_failed: status=500" in str(exc_info.value)
    updated = repository.get_connection()
    assert updated is not None
    assert updated.status == ConnectionStatus.ACTIVE


def test_refresh_rate_limit_keeps_connection_active(tmp_path):
    """refresh 429 は connection status を更新せず安全な診断で例外を投げる。"""
    # Arrange
    repository, cipher, connection = _repository_with_token(tmp_path, expired=True)
    session = FakeSession([FakeResponse({}, status_code=429)] * 3)
    client = GoogleHealthAPIClient(
        repository,
        cipher,
        client_id="client-id",
        client_secret="client-secret",
        session=session,
        sleep=lambda _: None,
    )

    # Act & Assert
    with pytest.raises(GoogleHealthAuthenticationError) as exc_info:
        client.list_data_points(connection.connection_id, "steps")

    assert "oauth_refresh_failed: status=429" in str(exc_info.value)
    updated = repository.get_connection()
    assert updated is not None
    assert updated.status == ConnectionStatus.ACTIVE
