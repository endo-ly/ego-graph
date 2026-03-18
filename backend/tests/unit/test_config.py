"""Config層のテスト。"""

from unittest.mock import patch

import pytest
from pydantic import SecretStr, ValidationError

from backend.config import BackendConfig, LLMConfig


class TestLLMConfig:
    """LLMConfigのテスト。"""

    def test_default_values(self):
        """デフォルト値の検証。"""
        # Arrange & Act: model_construct()を使ってデフォルト値で構築
        config = LLMConfig.model_construct()

        # Assert: デフォルト値を検証
        assert config.default_model == "deepseek/deepseek-v3.2"
        assert config.temperature == 0.7
        assert config.max_tokens == 2048
        assert config.enable_web_search is False

    def test_custom_values(self):
        """カスタム値の設定。"""
        # Arrange & Act: カスタム値でLLMConfigを構築
        config = LLMConfig.model_construct(
            openai_api_key=SecretStr("sk-test-openai"),
            anthropic_api_key=SecretStr("sk-ant-test-anthropic"),
            openrouter_api_key=SecretStr("sk-or-test-openrouter"),
            default_model="gpt-4o-mini",
            temperature=0.5,
            max_tokens=4096,
            enable_web_search=True,
        )

        # Assert: カスタム値が正しく設定されることを検証
        assert config.default_model == "gpt-4o-mini"
        assert config.temperature == 0.5
        assert config.max_tokens == 4096
        assert config.enable_web_search is True

    def test_all_api_keys_are_optional(self):
        """API Keyは任意であることを確認。"""
        # Arrange & Act: APIキーなしで作成可能
        config = LLMConfig.model_construct()

        # Assert: 全てのAPIキーがNoneであることを検証
        assert config.openai_api_key is None
        assert config.anthropic_api_key is None
        assert config.openrouter_api_key is None

    def test_api_keys_are_secret(self):
        """API Keyが SecretStr として扱われる。"""
        # Arrange & Act: SecretStrでラップしたAPI KeyでLLMConfigを構築
        config = LLMConfig.model_construct(
            openai_api_key=SecretStr("sk-test-key"),
        )

        # Assert: API KeyがSecretStrとして扱われることを検証
        assert isinstance(config.openai_api_key, SecretStr)
        assert config.openai_api_key.get_secret_value() == "sk-test-key"

    def test_get_api_key_openai(self):
        """OpenAIのAPIキーを取得できる。"""
        # Arrange
        config = LLMConfig.model_construct(
            openai_api_key=SecretStr("sk-test-openai"),
        )

        # Act
        api_key = config.get_api_key("openai")

        # Assert
        assert api_key == "sk-test-openai"

    def test_get_api_key_anthropic(self):
        """AnthropicのAPIキーを取得できる。"""
        # Arrange
        config = LLMConfig.model_construct(
            anthropic_api_key=SecretStr("sk-ant-test"),
        )

        # Act
        api_key = config.get_api_key("anthropic")

        # Assert
        assert api_key == "sk-ant-test"

    def test_get_api_key_openrouter(self):
        """OpenRouterのAPIキーを取得できる。"""
        # Arrange
        config = LLMConfig.model_construct(
            openrouter_api_key=SecretStr("sk-or-test"),
        )

        # Act
        api_key = config.get_api_key("openrouter")

        # Assert
        assert api_key == "sk-or-test"

    def test_get_api_key_missing_raises_error(self):
        """APIキーが未設定の場合にエラーが発生する。"""
        # Arrange
        config = LLMConfig.model_construct()

        # Act & Assert
        with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
            config.get_api_key("openai")

    def test_get_api_key_unsupported_provider_raises_error(self):
        """未対応のプロバイダーでエラーが発生する。"""
        # Arrange
        config = LLMConfig.model_construct()

        # Act & Assert
        with pytest.raises(ValueError, match="Unsupported provider: unknown"):
            config.get_api_key("unknown")

    def test_get_api_key_case_insensitive(self):
        """プロバイダー名の大文字小文字を区別しない。"""
        # Arrange
        config = LLMConfig.model_construct(
            openai_api_key=SecretStr("sk-test"),
        )

        # Act & Assert: 大文字小文字が違っても同じAPIキーが返される
        assert config.get_api_key("OpenAI") == "sk-test"
        assert config.get_api_key("OPENAI") == "sk-test"
        assert config.get_api_key("openai") == "sk-test"


class TestBackendConfig:
    """BackendConfigのテスト。"""

    def test_default_values(self):
        """デフォルト値の検証。"""
        # Arrange & Act: デフォルト値でBackendConfigを構築
        config = BackendConfig.model_construct()

        # Assert: デフォルト値を検証
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.reload is True
        assert config.log_level == "INFO"
        assert config.api_key is None
        assert config.llm is None
        assert config.r2 is None

    def test_custom_values(self):
        """カスタム値の設定。"""
        # Arrange & Act: カスタム値でBackendConfigを構築
        config = BackendConfig.model_construct(
            host="0.0.0.0",
            port=9000,
            reload=False,
            api_key=SecretStr("custom-key"),  # SecretStrでラップして渡す
            log_level="DEBUG",
        )

        # Assert: カスタム値が正しく設定されることを検証
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.reload is False
        assert config.api_key.get_secret_value() == "custom-key"
        assert config.log_level == "DEBUG"
        assert config.r2 is None

    def test_from_env_missing_r2_raises_error(self):
        """R2設定が不足している場合のエラー。"""
        # Arrange: R2Settings()の初期化をモックしてValidationErrorを発生させる

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

            # Act & Assert: R2設定不足時にValueErrorが発生することを検証
            with pytest.raises(ValueError, match="R2 configuration is missing"):
                BackendConfig.from_env()

    def test_from_env_with_r2_only(self, monkeypatch):
        """R2設定のみでロード可能（LLMは任意）。"""
        # Arrange: R2環境変数を設定
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")
        monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")

        # Act: 環境変数からConfigをロード
        config = BackendConfig.from_env()

        # Assert: R2のみが設定されることを検証（LLMはデフォルト値で作成される）
        assert config.r2 is not None
        assert config.r2.bucket_name == "test-bucket"
        # LLMConfigは必須フィールドがないため常に作成される（APIキーはNone）

    def test_from_env_with_llm_and_r2(self, monkeypatch):
        """LLMとR2の両方が設定されている場合。"""
        # Arrange: R2とLLMの環境変数を設定
        # R2環境変数
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")
        monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")

        # LLM環境変数（新しい形式）
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-anthropic")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-openrouter")

        # Act: 環境変数からConfigをロード
        config = BackendConfig.from_env()

        # Assert: R2とLLM両方が設定されることを検証
        assert config.r2 is not None
        assert config.llm is not None
        assert config.llm.openai_api_key is not None
        assert config.llm.openai_api_key.get_secret_value() == ("sk-test-openai")
        assert config.llm.anthropic_api_key is not None
        assert config.llm.anthropic_api_key.get_secret_value() == (
            "sk-ant-test-anthropic"
        )
        assert config.llm.openrouter_api_key is not None
        assert config.llm.openrouter_api_key.get_secret_value() == (
            "sk-or-test-openrouter"
        )

    def test_validate_for_production_with_api_key_and_llm(self, mock_backend_config):
        """API KeyとLLMがあれば本番環境検証成功。"""
        # Arrange: mock_backend_configにはすでにapi_keyとllmが設定されている

        # Act: 本番環境検証を実行
        mock_backend_config.validate_for_production()

        # Assert: エラーが発生しないことを検証（実行が完了すればOK）

    def test_validate_for_production_missing_api_key(self, mock_backend_config):
        """API Keyがなければ本番環境検証失敗。"""
        # Arrange: API Keyを削除
        mock_backend_config.api_key = None

        # Act & Assert: API Key不足でValueErrorが発生することを検証
        with pytest.raises(ValueError, match="BACKEND_API_KEY is required"):
            mock_backend_config.validate_for_production()

    def test_validate_for_production_missing_llm(self, mock_backend_config):
        """LLMがなければ本番環境検証失敗。"""
        # Arrange: LLM設定を削除
        mock_backend_config.llm = None

        # Act & Assert: LLM設定不足でValueErrorが発生することを検証
        with pytest.raises(ValueError, match="LLM configuration is required"):
            mock_backend_config.validate_for_production()
