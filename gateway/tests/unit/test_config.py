"""設定管理モジュールの単体テスト。"""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from gateway.config import GatewayConfig, is_allowed_client_ip, is_tailscale_ip

MOCK_TAILSCALE_ORIGIN = "https://mock-gateway.test.ts.net"

# ============================================================================
# GatewayConfigテスト
# ============================================================================


class TestGatewayConfig:
    """GatewayConfigクラスのテスト。"""

    def test_config_loads_default_values(self):
        """デフォルト値が正しくロードされることを確認する。"""
        # Arrange
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "test_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "test_webhook_secret_32_bytes_or_more",
        }

        # Act
        with patch.dict("os.environ", env_vars, clear=True):
            config = GatewayConfig(_env_file=None)

        # Assert
        assert config.host == "0.0.0.0"
        assert config.port == 8001
        assert config.api_key.get_secret_value() == "test_api_key_32_bytes_or_more"
        assert (
            config.webhook_secret.get_secret_value()
            == "test_webhook_secret_32_bytes_or_more"
        )
        assert config.cors_origins == ""
        assert config.log_level == "INFO"
        assert config.reload is False
        assert config.fcm_project_id is None
        assert config.fcm_credentials_path == "gateway/firebase-service-account.json"
        assert config.default_user_id == "default_user"
        assert config.session_pattern == r"^agent-[0-9]{4}$"
        assert config.terminal_ws_token_ttl_seconds == 60

    def test_config_loads_from_environment_variables(self):
        """環境変数から設定が正しくロードされることを確認する。"""
        # Arrange
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_HOST": "127.0.0.1",
            "GATEWAY_PORT": "9001",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "CORS_ORIGINS": MOCK_TAILSCALE_ORIGIN,
            "LOG_LEVEL": "DEBUG",
            "GATEWAY_RELOAD": "true",
            "FCM_PROJECT_ID": "test-project",
            "FCM_CREDENTIALS_PATH": "gateway/custom-firebase.json",
            "DEFAULT_USER_ID": "test_user",
            "SESSION_PATTERN": r"^test-[0-9]+$",
            "TERMINAL_WS_TOKEN_TTL_SECONDS": "45",
        }

        # Act
        with patch.dict("os.environ", env_vars, clear=True):
            config = GatewayConfig(_env_file=None)

        # Assert
        assert config.host == "127.0.0.1"
        assert config.port == 9001
        assert config.api_key.get_secret_value() == "env_api_key_32_bytes_or_more"
        assert (
            config.webhook_secret.get_secret_value()
            == "env_webhook_secret_32_bytes_or_more"
        )
        assert config.cors_origins == MOCK_TAILSCALE_ORIGIN
        assert config.log_level == "DEBUG"
        assert config.reload is True
        assert config.fcm_project_id == "test-project"
        assert config.fcm_credentials_path == "gateway/custom-firebase.json"
        assert config.default_user_id == "test_user"
        assert config.session_pattern == r"^test-[0-9]+$"
        assert config.terminal_ws_token_ttl_seconds == 45

    def test_config_rejects_too_small_ws_token_ttl(self):
        """TERMINAL_WS_TOKEN_TTL_SECONDS が下限未満の場合はエラーになることを確認する。"""
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "TERMINAL_WS_TOKEN_TTL_SECONDS": "29",
        }

        with patch.dict("os.environ", env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                GatewayConfig(_env_file=None)

        assert "TERMINAL_WS_TOKEN_TTL_SECONDS" in str(exc_info.value)

    def test_config_rejects_too_large_ws_token_ttl(self):
        """TERMINAL_WS_TOKEN_TTL_SECONDS が上限超過の場合はエラーになることを確認する。"""
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "TERMINAL_WS_TOKEN_TTL_SECONDS": "121",
        }

        with patch.dict("os.environ", env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                GatewayConfig(_env_file=None)

        assert "TERMINAL_WS_TOKEN_TTL_SECONDS" in str(exc_info.value)

    def test_config_accepts_min_ws_token_ttl(self):
        """TERMINAL_WS_TOKEN_TTL_SECONDS が下限(30秒)を受け入れることを確認する。"""
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "TERMINAL_WS_TOKEN_TTL_SECONDS": "30",
        }

        with patch.dict("os.environ", env_vars, clear=True):
            config = GatewayConfig(_env_file=None)

        assert config.terminal_ws_token_ttl_seconds == 30

    def test_config_accepts_max_ws_token_ttl(self):
        """TERMINAL_WS_TOKEN_TTL_SECONDS が上限(120秒)を受け入れることを確認する。"""
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "TERMINAL_WS_TOKEN_TTL_SECONDS": "120",
        }

        with patch.dict("os.environ", env_vars, clear=True):
            config = GatewayConfig(_env_file=None)

        assert config.terminal_ws_token_ttl_seconds == 120

    def test_config_rejects_non_tailscale_cors_origins(self):
        """CORS_ORIGINS が Tailscale 以外の場合はエラーになることを確認する。"""
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "CORS_ORIGINS": "https://example.com",
        }

        with patch.dict("os.environ", env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                GatewayConfig(_env_file=None)

        assert "CORS_ORIGINS" in str(exc_info.value)

    def test_config_accepts_wildcard_cors_origins(self):
        """CORS_ORIGINS のワイルドカード指定を受け入れることを確認する。"""
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "CORS_ORIGINS": "*",
        }

        with patch.dict("os.environ", env_vars, clear=True):
            config = GatewayConfig(_env_file=None)

        assert config.cors_origins == "*"

    def test_config_rejects_mixed_wildcard_and_specific_cors_origins(self):
        """CORS_ORIGINS のワイルドカードと個別指定の混在を拒否することを確認する。"""
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "env_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "env_webhook_secret_32_bytes_or_more",
            "CORS_ORIGINS": f"*,{MOCK_TAILSCALE_ORIGIN}",
        }

        with patch.dict("os.environ", env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                GatewayConfig(_env_file=None)

        assert "CORS_ORIGINS" in str(exc_info.value)

    def test_config_requires_api_key(self):
        """必須のAPIキーが未設定の場合はバリデーションエラーになることを確認する。"""
        # Arrange
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_WEBHOOK_SECRET": "test_webhook_secret_32_bytes_or_more",
        }

        # Act & Assert
        with patch.dict("os.environ", env_vars, clear=True):
            import importlib

            import gateway.config as config_module

            importlib.reload(config_module)
            with pytest.raises(ValidationError) as exc_info:
                config_module.GatewayConfig()

        assert "GATEWAY_API_KEY" in str(exc_info.value)

    def test_config_requires_webhook_secret(self):
        """必須のWebhookシークレットが未設定の場合はバリデーションエラーになることを確認する。"""
        # Arrange
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "test_api_key_32_bytes_or_more",
        }

        # Act & Assert
        with patch.dict("os.environ", env_vars, clear=True):
            import importlib

            import gateway.config as config_module

            importlib.reload(config_module)
            with pytest.raises(ValidationError) as exc_info:
                config_module.GatewayConfig()

        assert "GATEWAY_WEBHOOK_SECRET" in str(exc_info.value)

    def test_config_secret_str_hides_values(self):
        """SecretStrが値を隠蔽することを確認する。"""
        # Arrange
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "secret_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "secret_webhook_32_bytes_or_more",
        }

        # Act
        with patch.dict("os.environ", env_vars, clear=True):
            config = GatewayConfig(_env_file=None)

        # Assert
        # 文字列表現では値が隠蔽される
        assert "secret_key_32_bytes_or_more" not in str(config.api_key)
        assert "secret_webhook_32_bytes_or_more" not in str(config.webhook_secret)
        # get_secret_value()で実際の値を取得できる
        assert config.api_key.get_secret_value() == "secret_key_32_bytes_or_more"
        assert (
            config.webhook_secret.get_secret_value()
            == "secret_webhook_32_bytes_or_more"
        )

    def test_from_env_loads_config_and_sets_up_logging(self):
        """from_envで設定をロードしロギングが設定されることを確認する。"""
        # Arrange
        env_vars = {
            "USE_ENV_FILE": "false",
            "GATEWAY_API_KEY": "test_api_key_32_bytes_or_more",
            "GATEWAY_WEBHOOK_SECRET": "test_webhook_secret_32_bytes_or_more",
            "CORS_ORIGINS": MOCK_TAILSCALE_ORIGIN,
            "LOG_LEVEL": "DEBUG",
        }

        # Act
        with patch.dict("os.environ", env_vars, clear=True):
            config = GatewayConfig.from_env()

        # Assert
        assert config.log_level == "DEBUG"
        assert config.api_key.get_secret_value() == "test_api_key_32_bytes_or_more"


# ============================================================================
# モジュール定数テスト
# ============================================================================


class TestModuleConstants:
    """モジュール定数のテスト。"""

    def test_use_env_file_default(self):
        """USE_ENV_FILEのデフォルト値を確認する。"""
        # Arrange & Act & Assert
        with patch.dict("os.environ", {}, clear=True):
            import importlib

            import gateway.config as config_module

            importlib.reload(config_module)
            assert config_module.USE_ENV_FILE is True

    def test_use_env_file_can_be_disabled(self):
        """USE_ENV_FILEが環境変数で無効化できることを確認する。"""
        # Arrange & Act & Assert
        with patch.dict("os.environ", {"USE_ENV_FILE": "false"}, clear=True):
            import importlib

            import gateway.config as config_module

            importlib.reload(config_module)
            assert config_module.USE_ENV_FILE is False

    def test_gateway_env_files_when_enabled(self):
        """USE_ENV_FILEが有効な場合にGATEWAY_ENV_FILESが設定されることを確認する。"""
        # Arrange & Act & Assert
        with patch.dict("os.environ", {}, clear=True):
            import importlib

            import gateway.config as config_module

            importlib.reload(config_module)
            assert config_module.GATEWAY_ENV_FILES == ["gateway/.env"]

    def test_gateway_env_files_when_disabled(self):
        """USE_ENV_FILEが無効な場合にGATEWAY_ENV_FILESが空になることを確認する。"""
        # Arrange & Act & Assert
        with patch.dict("os.environ", {"USE_ENV_FILE": "false"}, clear=True):
            import importlib

            import gateway.config as config_module

            importlib.reload(config_module)
            assert config_module.GATEWAY_ENV_FILES == []


class TestNetworkValidationHelpers:
    """ネットワーク検証ヘルパーのテスト。"""

    @pytest.mark.parametrize(
        ("ip", "expected"),
        [
            ("100.64.0.1", True),
            ("100.127.255.254", True),
            ("fd7a:115c:a1e0::1", True),
            ("192.168.1.10", False),
            ("8.8.8.8", False),
            ("invalid", False),
        ],
    )
    def test_is_tailscale_ip(self, ip: str, expected: bool):
        """is_tailscale_ip が Tailscale 範囲のみ真を返すことを確認する。"""
        assert is_tailscale_ip(ip) is expected

    @pytest.mark.parametrize(
        ("ip", "expected"),
        [
            ("127.0.0.1", True),
            ("::1", True),
            ("100.100.100.100", True),
            ("fd7a:115c:a1e0::1234", True),
            ("10.0.0.1", False),
            ("example.com", False),
        ],
    )
    def test_is_allowed_client_ip(self, ip: str, expected: bool):
        """is_allowed_client_ip が localhost と Tailnet のみ許可することを確認する。"""
        assert is_allowed_client_ip(ip) is expected
