"""Google Health connection API のテスト。"""

import logging
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pipelines.app import create_app
from pipelines.config import PipelinesConfig
from pipelines.infrastructure.logging_filters import OAuthCallbackAccessLogFilter
from pipelines.sources.google_health.auth import DEFAULT_SCOPES
from pipelines.sources.google_health.client import GoogleHealthRateLimitError
from pipelines.sources.google_health.models import ConnectionStatus
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
    else:
        values.update(
            {
                "google_health_client_id": None,
                "google_health_client_secret": None,
                "google_health_redirect_uri": None,
                "google_health_token_encryption_key": None,
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


def test_auth_callback_returns_standardized_invalid_detail(tmp_path):
    """OAuth callback の失敗は統一APIエラー形式で返す。"""
    # Arrange
    app = create_app(_config(tmp_path))

    # Act
    with TestClient(app) as client:
        response = client.get(
            "/v1/sources/google-health/auth/callback",
            params={"code": "code", "state": "unknown-state"},
        )

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "invalid_oauth_state: state is expired or already used"
    )


def test_google_health_api_error_returns_standardized_invalid_detail(tmp_path):
    """Google Health API failure は統一APIエラー形式で返す。"""
    # Arrange
    app = create_app(_config(tmp_path))
    service = app.state.service
    connection = type(
        "Connection",
        (),
        {"connection_id": "google-health-primary"},
    )()
    service.google_health_repository.get_connection = lambda: connection
    service.google_health_client.list_data_points = lambda *_: (_ for _ in ()).throw(
        GoogleHealthRateLimitError("google_health_rate_limit_exceeded")
    )

    # Act
    with TestClient(app) as client:
        response = client.post(
            "/v1/sources/google-health/connection/smoke-test",
            headers={"X-API-Key": "api-key"},
        )

    # Assert
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "invalid_request: google_health_rate_limit_exceeded"
    )


def test_google_health_configuration_rejects_blank_values(tmp_path):
    """空白のみのGoogle Health設定は未設定として扱う。"""
    # Arrange
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        google_health_client_id=SecretStr(" "),
        google_health_client_secret=SecretStr("\t"),
        google_health_redirect_uri="  ",
        google_health_token_encryption_key=SecretStr("\n"),
    )

    # Act & Assert
    assert config.google_health_is_configured is False


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


def test_create_range_ingest_run_preserves_request_context(tmp_path):
    """range run作成APIはclosed-open期間をrunへ保存する。"""
    # Arrange
    app = create_app(_config(tmp_path))
    service = app.state.service
    service.google_health_repository.get_connection = lambda: type(
        "Connection",
        (),
        {"status": ConnectionStatus.ACTIVE},
    )()

    # Act
    with TestClient(app) as client:
        response = client.post(
            "/v1/sources/google-health/runs",
            headers={"X-API-Key": "api-key"},
            json={
                "mode": "range",
                "from": "2026-06-01",
                "to": "2026-06-03",
            },
        )

    # Assert
    assert response.status_code == 201
    run = service.run_repository.get_run(response.json()["run_id"])
    assert run.workflow_id == "google_health_ingest_workflow"
    assert run.result_summary == {
        "request": {
            "mode": "range",
            "from": "2026-06-01",
            "to": "2026-06-03",
            "data_types": [],
        }
    }


def test_create_initial_backfill_resolves_ninety_day_range(tmp_path):
    """initial_backfillは実行時点までの90日をrunへ保存する。"""
    # Arrange
    app = create_app(_config(tmp_path))
    service = app.state.service
    service.google_health_repository.get_connection = lambda: type(
        "Connection",
        (),
        {"status": ConnectionStatus.ACTIVE},
    )()

    # Act
    with TestClient(app) as client:
        response = client.post(
            "/v1/sources/google-health/runs",
            headers={"X-API-Key": "api-key"},
            json={"mode": "initial_backfill"},
        )

    # Assert
    assert response.status_code == 201
    run = service.run_repository.get_run(response.json()["run_id"])
    request = run.result_summary["request"]
    assert request["mode"] == "initial_backfill"
    assert date.fromisoformat(request["to"]) - date.fromisoformat(
        request["from"]
    ) == timedelta(days=90)
    assert request["data_types"] == []


def test_create_data_type_range_preserves_selected_types(tmp_path):
    """data_type_rangeは指定data typeと期間をrunへ保存する。"""
    # Arrange
    app = create_app(_config(tmp_path))
    service = app.state.service
    service.google_health_repository.get_connection = lambda: type(
        "Connection",
        (),
        {"status": ConnectionStatus.ACTIVE},
    )()

    # Act
    with TestClient(app) as client:
        response = client.post(
            "/v1/sources/google-health/runs",
            headers={"X-API-Key": "api-key"},
            json={
                "mode": "data_type_range",
                "from": "2026-06-01",
                "to": "2026-06-03",
                "data_types": ["steps", "sleep"],
            },
        )

    # Assert
    assert response.status_code == 201
    run = service.run_repository.get_run(response.json()["run_id"])
    assert run.result_summary == {
        "request": {
            "mode": "data_type_range",
            "from": "2026-06-01",
            "to": "2026-06-03",
            "data_types": ["steps", "sleep"],
        }
    }


def test_create_data_type_range_requires_data_types(tmp_path):
    """data_type_rangeは対象data typeなしでは受理しない。"""
    # Arrange
    app = create_app(_config(tmp_path))

    # Act
    with TestClient(app) as client:
        response = client.post(
            "/v1/sources/google-health/runs",
            headers={"X-API-Key": "api-key"},
            json={
                "mode": "data_type_range",
                "from": "2026-06-01",
                "to": "2026-06-03",
            },
        )

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"].startswith("invalid_data_types:")
