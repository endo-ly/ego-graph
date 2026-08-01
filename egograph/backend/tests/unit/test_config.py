"""Config層のテスト。"""

from unittest.mock import patch

import pytest
from egograph_paths import PARQUET_DATA_DIR
from pydantic import SecretStr, ValidationError

from backend.config import BackendConfig, R2Settings
from backend.main import create_app


class TestBackendConfig:
    """BackendConfigのテスト。"""

    def test_default_values(self):
        """デフォルト値の検証。"""
        config = BackendConfig.model_construct()

        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.reload is True
        assert config.environment == "development"
        assert config.log_level == "INFO"
        assert config.api_key is None
        assert config.r2 is None

    def test_custom_values(self):
        """カスタム値の設定。"""
        config = BackendConfig.model_construct(
            host="0.0.0.0",
            port=9000,
            reload=False,
            environment="production",
            api_key=SecretStr("custom-key"),
            log_level="DEBUG",
        )

        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.reload is False
        assert config.environment == "production"
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
        monkeypatch.delenv("BACKEND_ENV", raising=False)
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")
        monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")

        config = BackendConfig.from_env()

        assert config.r2 is not None
        assert config.r2.bucket_name == "test-bucket"
        assert config.r2.local_parquet_root == str(PARQUET_DATA_DIR)

    def test_from_env_reads_backend_environment(self, monkeypatch):
        """BACKEND_ENVを環境変数からロードする。"""
        monkeypatch.setenv("BACKEND_ENV", "production")
        monkeypatch.setenv("BACKEND_API_KEY", "production-key")
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")

        config = BackendConfig.from_env()

        assert config.environment == "production"

    def test_does_not_load_local_env_file(self, monkeypatch, tmp_path):
        """リポジトリ配下の.envを設定ソースとして使用しない。"""
        env_file = tmp_path / "egograph/backend/.env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text(
            "BACKEND_ENV=production\nBACKEND_API_KEY=from-local-file\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("BACKEND_ENV", raising=False)
        monkeypatch.delenv("BACKEND_API_KEY", raising=False)

        config = BackendConfig()

        assert config.environment == "development"
        assert config.api_key is None

    @pytest.mark.parametrize("environment", ["prod", "Production", "production "])
    def test_from_env_rejects_unknown_backend_environment(
        self, monkeypatch, environment
    ):
        """BACKEND_ENVの値域外を拒否する。"""
        monkeypatch.setenv("BACKEND_ENV", environment)

        with pytest.raises(ValidationError):
            BackendConfig()

    def test_validate_for_production_with_api_key(self, mock_backend_config):
        """API Keyがあれば本番環境検証成功。"""
        mock_backend_config.validate_for_production()

    def test_validate_for_production_missing_api_key(self, mock_backend_config):
        """API Keyがなければ本番環境検証失敗。"""
        mock_backend_config.api_key = None

        with pytest.raises(ValueError, match="BACKEND_API_KEY is required"):
            mock_backend_config.validate_for_production()

    @pytest.mark.parametrize("api_key", ["", " ", "\t\n"])
    def test_validate_for_production_rejects_blank_api_key(
        self, mock_backend_config, api_key
    ):
        """空白だけのAPI Keyを本番環境で拒否する。"""
        mock_backend_config.api_key = SecretStr(api_key)

        with pytest.raises(ValueError, match="BACKEND_API_KEY is required"):
            mock_backend_config.validate_for_production()

    def test_validate_for_production_preserves_non_blank_api_key(
        self, mock_backend_config
    ):
        """空白を含んでも値のあるAPI Keyを有効として扱う。"""
        api_key = "  test-backend-key  "
        mock_backend_config.api_key = SecretStr(api_key)

        mock_backend_config.validate_for_production()

        assert mock_backend_config.api_key.get_secret_value() == api_key

    def test_validate_for_production_wildcard_cors(self, mock_backend_config):
        """ワイルドカードCORSは本番環境で禁止。"""
        mock_backend_config.cors_origins = "*"

        with pytest.raises(
            ValueError,
            match="CORS_ORIGINS must be explicitly configured",
        ):
            mock_backend_config.validate_for_production()

    @pytest.mark.parametrize(
        "cors_origins",
        ["", " ", "https://app.example.com,,https://admin.example.com"],
    )
    def test_validate_for_production_rejects_empty_cors_origin(
        self, mock_backend_config, cors_origins
    ):
        """空要素を含むCORS設定を本番環境で拒否する。"""
        mock_backend_config.cors_origins = cors_origins

        with pytest.raises(
            ValueError,
            match="CORS_ORIGINS must be explicitly configured with non-empty origins",
        ):
            mock_backend_config.validate_for_production()

    def test_validate_for_production_requires_r2(self, mock_backend_config):
        """R2設定がなければ本番環境検証に失敗する。"""
        mock_backend_config.r2 = None

        with pytest.raises(ValueError, match="R2 configuration is required"):
            mock_backend_config.validate_for_production()

    def test_create_app_rejects_invalid_production_config(self, mock_backend_config):
        """不正な本番設定ではFastAPIアプリを生成しない。"""
        mock_backend_config.environment = "production"
        mock_backend_config.api_key = None

        with pytest.raises(ValueError, match="BACKEND_API_KEY is required"):
            create_app(config=mock_backend_config)


class TestR2Settings:
    """R2Settings のテスト。"""

    def test_defaults_local_parquet_root_from_shared_paths(self, monkeypatch):
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")

        settings = R2Settings()

        assert settings.local_parquet_root == str(PARQUET_DATA_DIR)
