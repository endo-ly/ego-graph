"""Dataset catalog と manual compaction API のテスト。"""

import pytest
from fastapi.testclient import TestClient
from pipelines.api.dependencies import verify_api_key
from pipelines.app import create_app
from pipelines.config import PipelinesConfig
from pydantic import SecretStr


def _build_client(tmp_path):
    """外部設定に依存しない認証済みテストクライアントを構築する。"""
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=60,
        google_health_client_id=None,
        google_health_client_secret=None,
        google_health_redirect_uri=None,
        google_health_token_encryption_key=None,
        api_key=SecretStr("test-api-key"),
    )
    app = create_app(config)
    app.dependency_overrides[verify_api_key] = lambda: None
    return TestClient(app)


def test_list_datasets_returns_catalog_metadata(tmp_path):
    """dataset一覧はcatalogのIDとcompact対応可否を返す。"""
    # Arrange
    client = _build_client(tmp_path)

    # Act
    with client:
        response = client.get("/v1/datasets")

    # Assert
    assert response.status_code == 200
    datasets_by_id = {item["dataset_id"]: item for item in response.json()}
    assert datasets_by_id["github.commits"]["path"] == "github/commits"
    assert datasets_by_id["github.commits"]["compaction_supported"] is True
    assert datasets_by_id["google_health.samples"]["compaction_supported"] is False


def test_create_compaction_run_queues_selected_datasets(tmp_path):
    """指定したdataset partitionだけをmanual compaction runへ渡す。"""
    # Arrange
    payload = {
        "targets": [
            {"dataset_id": "github.commits", "year": 2026, "month": 7},
            {"dataset_id": "github.pull_requests", "year": 2026, "month": 7},
        ]
    }
    client = _build_client(tmp_path)

    # Act
    with client:
        response = client.post("/v1/compaction/runs", json=payload)

    # Assert
    assert response.status_code == 201
    run = response.json()
    assert run["workflow_id"] == "github_compact_workflow"
    assert run["status"] in {"queued", "running"}
    assert run["result_summary"] == {
        "compaction_targets": [
            {"dataset_id": "github.commits", "year": 2026, "month": 7},
            {"dataset_id": "github.pull_requests", "year": 2026, "month": 7},
        ]
    }


def test_create_compaction_run_rejects_unknown_dataset(tmp_path):
    """catalogにないdataset IDを拒否する。"""
    # Arrange
    payload = {"targets": [{"dataset_id": "unknown.dataset", "year": 2026, "month": 7}]}
    client = _build_client(tmp_path)

    # Act
    with client:
        response = client.post("/v1/compaction/runs", json=payload)

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"].startswith("invalid_dataset_id:")


def test_create_compaction_run_rejects_unsupported_compaction_strategy(tmp_path):
    """月次でも異なるcompaction strategyのdatasetを拒否する。"""
    # Arrange
    payload = {
        "targets": [
            {
                "dataset_id": "google_health.samples",
                "year": 2026,
                "month": 7,
            }
        ]
    }
    client = _build_client(tmp_path)

    # Act
    with client:
        response = client.post("/v1/compaction/runs", json=payload)

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"].startswith("invalid_dataset_id:")


@pytest.mark.parametrize("request_body", [[], "not-an-object", 1])
def test_create_compaction_run_rejects_non_object_body(tmp_path, request_body):
    """トップレベルの非オブジェクト入力を400へ変換する。"""
    # Arrange
    client = _build_client(tmp_path)

    # Act
    with client:
        response = client.post("/v1/compaction/runs", json=request_body)

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"].startswith("invalid_request:")


@pytest.mark.parametrize(
    ("field", "value"),
    [("year", "2026"), ("month", 7.0)],
)
def test_create_compaction_run_rejects_non_integer_period(field, value, tmp_path):
    """APIの期間値は厳密な整数だけを受け付ける。"""
    # Arrange
    target = {"dataset_id": "github.commits", "year": 2026, "month": 7}
    target[field] = value
    client = _build_client(tmp_path)

    # Act
    with client:
        response = client.post("/v1/compaction/runs", json={"targets": [target]})

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"].startswith(f"invalid_targets.0.{field}:")
