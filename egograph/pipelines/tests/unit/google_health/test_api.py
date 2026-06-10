"""Google Health connection API のテスト。"""

import logging
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pipelines.app import create_app
from pipelines.config import PipelinesConfig
from pipelines.infrastructure.logging_filters import OAuthCallbackAccessLogFilter
from pipelines.sources.google_health.auth import DEFAULT_SCOPES
from pydantic import SecretStr


def _config(tmp_path, *, configured=True):
    values = {
        "database_path": tmp_path / "state.sqlite3",
        "logs_root": tmp_path / "logs",
        "dispatcher_poll_seconds": 60,
        "api_key": SecretStr("api-key"),
    }
    if configured:
        values.update(
            {
                "google_health_client_id": SecretStr("client-id"),
                "google_health_client_secret": SecretStr("client-secret"),
                "google_health_redirect_uri": "https://example.test/callback",
                "google_health_token_encryption_key": SecretStr(
                    Fernet.generate_key().decode()
                ),
            }
        )
    return PipelinesConfig(**values)


def test_auth_start_returns_google_authorization_url(tmp_path):
    """auth start は Google 認可 URL を返す。"""
    # Arrange
    app = create_app(_config(tmp_path))

    # Act
    with TestClient(app) as client:
        response = client.get(
            "/v1/sources/google-health/auth/start",
            headers={"X-API-Key": "api-key"},
        )

    # Assert
    assert response.status_code == 200
    query = parse_qs(urlparse(response.json()["authorization_url"]).query)
    assert tuple(query["scope"][0].split()) == DEFAULT_SCOPES


def test_connection_returns_disconnected_and_delete_is_idempotent(tmp_path):
    """未接続状態の取得と削除は安全に実行できる。"""
    # Arrange
    app = create_app(_config(tmp_path))
    headers = {"X-API-Key": "api-key"}

    # Act
    with TestClient(app) as client:
        get_response = client.get(
            "/v1/sources/google-health/connection",
            headers=headers,
        )
        delete_response = client.delete(
            "/v1/sources/google-health/connection",
            headers=headers,
        )

    # Assert
    assert get_response.json() == {"connected": False, "status": None}
    assert delete_response.status_code == 204


def test_auth_start_rejects_incomplete_configuration(tmp_path):
    """OAuth 設定不足時は明示的な 503 を返す。"""
    # Arrange
    app = create_app(_config(tmp_path, configured=False))

    # Act
    with TestClient(app) as client:
        response = client.get(
            "/v1/sources/google-health/auth/start",
            headers={"X-API-Key": "api-key"},
        )

    # Assert
    assert response.status_code == 503
    assert response.json()["detail"].startswith("invalid_google_health_config:")


def test_oauth_callback_access_log_redacts_query_string():
    """OAuth callback の code/state は access log で伏せる。"""
    # Arrange
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1",
            "GET",
            "/v1/sources/google-health/auth/callback?code=secret&state=state",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    # Act
    OAuthCallbackAccessLogFilter().filter(record)

    # Assert
    assert "secret" not in record.getMessage()
    assert "state=state" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
