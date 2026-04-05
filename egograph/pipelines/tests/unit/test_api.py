from fastapi.testclient import TestClient
from pydantic import SecretStr

from pipelines.app import create_app
from pipelines.config import PipelinesConfig


def test_management_api_lists_workflows_and_manual_runs(tmp_path):
    """管理 API で workflow 一覧取得と手動 run enqueue ができる。"""
    # Arrange
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=60,
        api_key=SecretStr("test-api-key"),
    )
    app = create_app(config)
    h = {"X-API-Key": "test-api-key"}

    # Act & Assert
    with TestClient(app) as client:
        health_response = client.get("/v1/health")
        assert health_response.status_code == 200
        assert health_response.json() == {"status": "ok"}

        workflows_response = client.get("/v1/workflows", headers=h)
        assert workflows_response.status_code == 200
        workflow_ids = {
            workflow["workflow_id"] for workflow in workflows_response.json()
        }
        assert "spotify_ingest_workflow" in workflow_ids
        assert "github_ingest_workflow" in workflow_ids
        assert "google_activity_ingest_workflow" in workflow_ids

        disable_response = client.post(
            "/v1/workflows/spotify_ingest_workflow/disable",
            headers=h,
        )
        assert disable_response.status_code == 200
        assert disable_response.json()["enabled"] is False

        rejected_response = client.post(
            "/v1/workflows/spotify_ingest_workflow/runs",
            headers=h,
        )
        assert rejected_response.status_code == 400

        enable_response = client.post(
            "/v1/workflows/spotify_ingest_workflow/enable",
            headers=h,
        )
        assert enable_response.status_code == 200
        assert enable_response.json()["enabled"] is True

        run_response = client.post(
            "/v1/workflows/spotify_ingest_workflow/runs",
            headers=h,
        )
        assert run_response.status_code == 201
        run = run_response.json()
        assert run["workflow_id"] == "spotify_ingest_workflow"
        assert run["status"] == "queued"


def test_management_api_requires_api_key_when_configured(tmp_path):
    """PIPELINES_API_KEY 設定時は X-API-Key ヘッダーを必須にする。"""
    # Arrange
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=60,
        api_key=SecretStr("test-api-key"),
    )
    app = create_app(config)

    # Act & Assert
    with TestClient(app) as client:
        unauthorized_response = client.get("/v1/workflows")
        assert unauthorized_response.status_code == 401
        assert unauthorized_response.json() == {"detail": "Invalid API key"}

        authorized_response = client.get(
            "/v1/workflows",
            headers={"X-API-Key": "test-api-key"},
        )
        assert authorized_response.status_code == 200
        assert any(
            workflow["workflow_id"] == "spotify_ingest_workflow"
            for workflow in authorized_response.json()
        )
