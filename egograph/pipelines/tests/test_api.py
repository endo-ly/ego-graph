from fastapi.testclient import TestClient

from pipelines.app import create_app
from pipelines.config import PipelinesConfig


def test_management_api_lists_workflows_and_manual_runs(tmp_path):
    """管理 API で workflow 一覧取得と手動 run enqueue ができる。"""
    # Arrange
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=60,
    )
    app = create_app(config)

    # Act & Assert
    with TestClient(app) as client:
        health_response = client.get("/v1/health")
        assert health_response.status_code == 200
        assert health_response.json() == {"status": "ok"}

        workflows_response = client.get("/v1/workflows")
        assert workflows_response.status_code == 200
        workflows = workflows_response.json()
        assert any(
            workflow["workflow_id"] == "spotify_ingest_workflow"
            for workflow in workflows
        )

        disable_response = client.post("/v1/workflows/spotify_ingest_workflow/disable")
        assert disable_response.status_code == 200
        assert disable_response.json()["enabled"] is False

        rejected_response = client.post("/v1/workflows/spotify_ingest_workflow/runs")
        assert rejected_response.status_code == 400

        enable_response = client.post("/v1/workflows/spotify_ingest_workflow/enable")
        assert enable_response.status_code == 200
        assert enable_response.json()["enabled"] is True

        run_response = client.post("/v1/workflows/spotify_ingest_workflow/runs")
        assert run_response.status_code == 201
        run = run_response.json()
        assert run["workflow_id"] == "spotify_ingest_workflow"
        assert run["status"] == "queued"
