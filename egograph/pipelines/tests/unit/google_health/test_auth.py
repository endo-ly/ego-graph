"""Google Health OAuth のテスト。"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.sources.google_health.auth import GoogleHealthAuth
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

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class InvalidJSONResponse(FakeResponse):
    """JSON ではない token endpoint response。"""

    def json(self):
        raise ValueError("invalid JSON")


class FakeSession:
    """token endpoint 呼び出しを記録する。"""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, *, data, timeout):
        self.calls.append((url, data, timeout))
        return self.response


@pytest.fixture
def repository(tmp_path):
    """初期化済み repository を返す。"""
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    return GoogleHealthRepository(conn)


def _auth(repository, session):
    return GoogleHealthAuth(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.test/callback",
        repository=repository,
        token_cipher=TokenCipher(Fernet.generate_key().decode()),
        session=session,
    )


def test_start_authorization_builds_offline_consent_url(repository):
    """認可 URL は offline access と CSRF state を含む。"""
    # Arrange
    auth = _auth(repository, FakeSession(FakeResponse({})))

    # Act
    authorization_url = auth.start_authorization()
    query = parse_qs(urlparse(authorization_url).query)

    # Assert
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://example.test/callback"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert repository.consume_oauth_state(query["state"][0]) is True


def test_callback_exchanges_code_and_encrypts_tokens(repository):
    """callback は code を交換し token 平文を DB に残さない。"""
    # Arrange
    session = FakeSession(
        FakeResponse(
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "scope-a scope-b",
            }
        )
    )
    auth = _auth(repository, session)
    state = parse_qs(urlparse(auth.start_authorization()).query)["state"][0]

    # Act
    connection = auth.complete_authorization(code="secret-code", state=state)
    encrypted = repository.get_encrypted_token(connection.connection_id)

    # Assert
    assert connection.status.value == "active"
    assert encrypted is not None
    assert b"access-token" not in encrypted.access_token_encrypted
    assert b"refresh-token" not in encrypted.refresh_token_encrypted
    assert session.calls[0][1]["code"] == "secret-code"


def test_callback_rejects_reused_state(repository):
    """消費済み state は拒否する。"""
    # Arrange
    auth = _auth(repository, FakeSession(FakeResponse({})))
    state = parse_qs(urlparse(auth.start_authorization()).query)["state"][0]
    repository.consume_oauth_state(state)

    # Act & Assert
    with pytest.raises(ValueError, match="invalid_oauth_state"):
        auth.complete_authorization(code="secret-code", state=state)


def test_callback_classifies_invalid_token_response_body(repository):
    """token endpoint の非 JSON 応答を統一エラーに変換する。"""
    # Arrange
    auth = _auth(repository, FakeSession(InvalidJSONResponse(None)))
    state = parse_qs(urlparse(auth.start_authorization()).query)["state"][0]

    # Act & Assert
    with pytest.raises(
        ValueError,
        match="google_health_token_exchange_failed: invalid response body",
    ):
        auth.complete_authorization(code="secret-code", state=state)


def test_expired_oauth_state_is_rejected(repository):
    """期限切れ state は拒否する。"""
    # Arrange
    repository.save_oauth_state(
        "expired-state",
        datetime.now(tz=UTC) - timedelta(seconds=1),
    )

    # Act & Assert
    assert repository.consume_oauth_state("expired-state") is False
