"""API dependencies のテスト。"""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pipelines.api.dependencies import verify_api_key
from pipelines.app import create_app
from pipelines.config import PipelinesConfig


def _build_app(api_key: str | None = None, tmp_path=None):
    """テスト用アプリを構築する。"""
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=60,
        api_key=SecretStr(api_key) if api_key else None,
    )
    return create_app(config)


def test_verify_api_key_returns_500_when_no_key_configured(tmp_path):
    """api_key が未設定時は 500 を返す。"""
    app = _build_app(api_key=None, tmp_path=tmp_path)

    @app.get("/test")
    def test_endpoint(_: None = Depends(verify_api_key)):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 500
        assert response.json() == {"detail": "PIPELINES_API_KEY is not configured"}


def test_verify_api_key_rejects_missing_header(tmp_path):
    """api_key 設定時に X-API-Key がない場合 401 を返す。"""
    app = _build_app(api_key="secret-key", tmp_path=tmp_path)

    @app.get("/test")
    def test_endpoint(_: None = Depends(verify_api_key)):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test")
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


def test_verify_api_key_rejects_wrong_key(tmp_path):
    """api_key 設定時に誤ったキーの場合 401 を返す。"""
    app = _build_app(api_key="secret-key", tmp_path=tmp_path)

    @app.get("/test")
    def test_endpoint(_: None = Depends(verify_api_key)):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid API key"}


def test_verify_api_key_accepts_correct_key(tmp_path):
    """正しい X-API-Key で通過する。"""
    app = _build_app(api_key="secret-key", tmp_path=tmp_path)

    @app.get("/test")
    def test_endpoint(_: None = Depends(verify_api_key)):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test", headers={"X-API-Key": "secret-key"})
        assert response.status_code == 200


def test_verify_api_key_rejects_empty_key(tmp_path):
    """空文字列の X-API-Key は拒否する。"""
    app = _build_app(api_key="secret-key", tmp_path=tmp_path)

    @app.get("/test")
    def test_endpoint(_: None = Depends(verify_api_key)):
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/test", headers={"X-API-Key": ""})
        assert response.status_code == 401
