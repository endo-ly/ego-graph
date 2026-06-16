"""FastAPI依存関数のテスト。"""

import pytest
from fastapi import HTTPException

from backend.config import BackendConfig
from backend.dependencies import get_google_health_repository


def test_google_health_repository_rejects_missing_r2_with_api_error():
    """R2設定不足を統一APIエラーへ変換する。"""
    # Arrange
    config = BackendConfig(r2=None)

    # Act
    with pytest.raises(HTTPException) as exc_info:
        get_google_health_repository(config)

    # Assert
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == ("invalid_r2_config: R2 configuration is required")
