"""Config層のテスト。"""

from unittest.mock import patch

import pytest
from egograph_paths import PARQUET_DATA_DIR
from pydantic import SecretStr, ValidationError

from backend.config import BackendConfig, R2Settings


class TestBackendConfig:
    """BackendConfigのテスト。"""

    def test_default_values(self):
        """デフォルト値の検証。"""
        config = BackendConfig.model_construct()

        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.reload is True
        assert config.log_level == "INFO"
        assert config.api_key is None
        assert config.r2 is None

    def test_custom_values(self):
        """カスタム値の設定。"""
        config = BackendConfig.model_construct(
            host="0.0.0.0",
            port=9000,
            reload=False,
            api_key=SecretStr("custom-key"),
            log_level="DEBUG",
        )

        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.reload is False
        assert config.api_key.get_secret_value() == "custom-key"
        assert config.log_level == "DEBUG"
        assert config.r2 is None

    def test_from_env_missing_r2_raises_error(self):
        """R2設定が不足している場合のエラー。"""
        with patch("backend.config.R2Settings") as mock_r2_settings:
            mock_r2_settings.side_effect = ValidationError.from_exception_data(
                "R2Settings",
                [
                    {
                        "type": "missing",
                        "loc": ("R2_ENDPOINT_URL",),
                        "msg": "Field required",
                        "input": {},
                    }
                ],
            )

            with pytest.raises(ValueError, match="R2 configuration is missing"):
                BackendConfig.from_env()

    def test_from_env_with_r2_only(self, monkeypatch):
        """R2設定のみでロード可能。"""
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")
        monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")

        config = BackendConfig.from_env()

        assert config.r2 is not None
        assert config.r2.bucket_name == "test-bucket"
        assert config.r2.local_parquet_root == str(PARQUET_DATA_DIR)

    def test_validate_for_production_with_api_key(self, mock_backend_config):
        """API Keyがあれば本番環境検証成功。"""
        mock_backend_config.validate_for_production()

    def test_validate_for_production_missing_api_key(self, mock_backend_config):
        """API Keyがなければ本番環境検証失敗。"""
        mock_backend_config.api_key = None

        with pytest.raises(ValueError, match="BACKEND_API_KEY is required"):
            mock_backend_config.validate_for_production()

    def test_validate_for_production_wildcard_cors(self, mock_backend_config):
        """ワイルドカードCORSは本番環境で禁止。"""
        mock_backend_config.cors_origins = "*"

        with pytest.raises(
            ValueError,
            match="CORS_ORIGINS must be explicitly configured",
        ):
            mock_backend_config.validate_for_production()


class TestR2Settings:
    """R2Settings のテスト。"""

    def test_defaults_local_parquet_root_from_shared_paths(self, monkeypatch):
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")

        settings = R2Settings()

        assert settings.local_parquet_root == str(PARQUET_DATA_DIR)
