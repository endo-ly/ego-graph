"""backend.main モジュールレベルの検証。

uvicorn が `backend.main:app` を参照するため、
モジュールレベルの `app` 変数が常に存在することを保証する。
"""

from fastapi import FastAPI


def test_module_level_app_is_fastapi():
    """backend.main:app が FastAPI インスタンスである。"""
    # Arrange & Act
    from backend.main import app

    # Assert
    assert isinstance(app, FastAPI)


def test_module_level_app_has_routes():
    """app にルーターが登録されている。"""
    # Arrange
    from backend.main import app

    # Act
    route_paths = [getattr(route, "path", "") for route in app.routes]

    # Assert: 基本エンドポイントが含まれる
    assert "/health" in route_paths
    assert "/mcp" in route_paths or any("/mcp" in p for p in route_paths if p)
