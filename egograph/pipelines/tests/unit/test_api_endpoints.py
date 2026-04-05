"""Workflow / Runs API のエラーパスと境界条件テスト。"""

from fastapi.testclient import TestClient
from pydantic import SecretStr

from pipelines.api.dependencies import verify_api_key
from pipelines.app import create_app
from pipelines.config import PipelinesConfig


def _build_client(tmp_path):
    """認証をバイパスしたテストクライアントを構築する。"""
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=60,
    )
    app = create_app(config)
    app.dependency_overrides[verify_api_key] = lambda: None
    return TestClient(app)


# --- workflows.py ---


def test_get_workflow_404(tmp_path):
    """存在しない workflow_id で 404 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.get("/v1/workflows/nonexistent_workflow")
        assert response.status_code == 404


def test_get_workflow_runs_for_unknown_workflow(tmp_path):
    """存在しない workflow_id の run 一覧は空リストを返す。"""
    with _build_client(tmp_path) as client:
        response = client.get("/v1/workflows/nonexistent_workflow/runs")
        assert response.status_code == 200
        assert response.json() == []


def test_create_workflow_run_400_for_unknown_workflow(tmp_path):
    """存在しない workflow_id の手動実行は 400 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.post("/v1/workflows/nonexistent_workflow/runs")
        assert response.status_code == 400


def test_enable_workflow_404(tmp_path):
    """存在しない workflow_id の有効化は 404 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.post("/v1/workflows/nonexistent_workflow/enable")
        assert response.status_code == 404


def test_disable_workflow_404(tmp_path):
    """存在しない workflow_id の無効化は 404 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.post("/v1/workflows/nonexistent_workflow/disable")
        assert response.status_code == 404


# --- runs.py ---


def test_list_runs_empty(tmp_path):
    """run が一件もない場合、空リストを返す。"""
    with _build_client(tmp_path) as client:
        response = client.get("/v1/runs")
        assert response.status_code == 200
        assert response.json() == []


def test_get_run_404(tmp_path):
    """存在しない run_id で 404 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.get("/v1/runs/nonexistent-run-id")
        assert response.status_code == 404


def test_get_step_log_404(tmp_path):
    """存在しない run/step のログで 404 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.get("/v1/runs/nonexistent-run-id/steps/step-1/log")
        assert response.status_code == 404


def test_retry_run_400_for_unknown_run(tmp_path):
    """存在しない run_id のリトライは 400 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.post("/v1/runs/nonexistent-run-id/retry")
        assert response.status_code == 400


def test_cancel_run_400_for_unknown_run(tmp_path):
    """存在しない run_id のキャンセルは 400 を返す。"""
    with _build_client(tmp_path) as client:
        response = client.post("/v1/runs/nonexistent-run-id/cancel")
        assert response.status_code == 400


def test_retry_run_creates_new_queued_run(tmp_path):
    """成功した run のリトライは新しい queued run を作成する。"""
    with _build_client(tmp_path) as client:
        # 手動 run を作成
        run_response = client.post("/v1/workflows/spotify_ingest_workflow/runs")
        assert run_response.status_code == 201
        run_id = run_response.json()["run_id"]

        # リトライ実行
        retry_response = client.post(f"/v1/runs/{run_id}/retry")
        assert retry_response.status_code == 201
        retry_run = retry_response.json()
        assert retry_run["workflow_id"] == "spotify_ingest_workflow"
        assert retry_run["status"] == "queued"
        assert retry_run["parent_run_id"] == run_id


def test_cancel_run_idempotent_for_non_queued_run(tmp_path):
    """queued 以外の run のキャンセルは現在の状態をそのまま返す（冪等）。"""
    with _build_client(tmp_path) as client:
        # 手動 run を作成 (queued 状態)
        run_response = client.post("/v1/workflows/spotify_ingest_workflow/runs")
        assert run_response.status_code == 201
        run_id = run_response.json()["run_id"]

        # cancel 実行
        cancel_response = client.post(f"/v1/runs/{run_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "canceled"

        # 既にcanceledなので再度cancelしても同じ状態が返る（冪等）
        cancel_again = client.post(f"/v1/runs/{run_id}/cancel")
        assert cancel_again.status_code == 200
        assert cancel_again.json()["status"] == "canceled"
