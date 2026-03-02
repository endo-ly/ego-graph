"""Gateway 設定管理。

認証トークン、サーバー設定、Webhook シークレットなどを管理します。
"""

import logging
import os
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 環境変数で .env ファイルの使用を制御（デフォルトは使用）
USE_ENV_FILE = os.getenv("USE_ENV_FILE", "true").lower() in ("true", "1", "yes")
GATEWAY_ENV_FILES = ["gateway/.env"] if USE_ENV_FILE else []
LOCAL_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
TAILSCALE_IP_RANGES = (
    ip_network("100.64.0.0/10"),
    ip_network("fd7a:115c:a1e0::/48"),
)


def is_tailscale_hostname(hostname: str) -> bool:
    """Tailscale のマジックドメインかどうかを判定する。"""
    host = hostname.strip().lower().rstrip(".")
    return host.endswith(".ts.net")


def is_tailscale_ip(value: str) -> bool:
    """IP が Tailscale 割り当て範囲かどうかを判定する。"""
    try:
        address = ip_address(value.strip())
    except ValueError:
        return False
    return any(address in network for network in TAILSCALE_IP_RANGES)


def is_allowed_client_ip(value: str) -> bool:
    """接続元IPが許可対象（localhost または Tailnet）か判定する。"""
    try:
        address = ip_address(value.strip())
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return is_tailscale_ip(value)


class GatewayConfig(BaseSettings):
    """Gateway サーバー設定。

    サーバー設定、認証トークン、Webhook シークレットを管理します。
    """

    model_config = SettingsConfigDict(
        env_file=GATEWAY_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # サーバー設定
    host: str = Field("0.0.0.0", alias="GATEWAY_HOST")
    port: int = Field(8001, alias="GATEWAY_PORT")

    # 認証キー（必須、32バイト以上推奨）
    api_key: SecretStr = Field(..., alias="GATEWAY_API_KEY")

    # Webhook シークレット（必須、32バイト以上推奨）
    webhook_secret: SecretStr = Field(..., alias="GATEWAY_WEBHOOK_SECRET")

    # CORS設定（空は無効、"*"はワイルドカード、それ以外は https://*.ts.net のみ）
    cors_origins: str = Field("", alias="CORS_ORIGINS")

    # ロギング
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # 開発用リロード（本番では false 推奨）
    reload: bool = Field(False, alias="GATEWAY_RELOAD")

    # FCM プロジェクト ID（オプション）
    fcm_project_id: str | None = Field(None, alias="FCM_PROJECT_ID")

    # FCM サービスアカウント JSON パス（省略時は固定パスを使用）
    fcm_credentials_path: str = Field(
        "gateway/firebase-service-account.json",
        alias="FCM_CREDENTIALS_PATH",
    )

    # デフォルトユーザー ID（MVP では固定）
    default_user_id: str = Field("default_user", alias="DEFAULT_USER_ID")

    # tmux セッション名の正規表現パターン
    session_pattern: str = Field(r"^agent-[0-9]{4}$", alias="SESSION_PATTERN")

    # WebSocket トークン TTL（秒）
    terminal_ws_token_ttl_seconds: int = Field(
        60,
        alias="TERMINAL_WS_TOKEN_TTL_SECONDS",
        ge=30,
        le=120,
    )

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        """CORS_ORIGINS を検証し、正規化した文字列を返す。"""
        if not value or not value.strip():
            return ""

        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if "*" in origins:
            if len(origins) > 1:
                raise ValueError("CORS_ORIGINS wildcard '*' must be used alone")
            return "*"

        normalized: list[str] = []
        for origin in origins:
            parsed = urlparse(origin)
            host = (parsed.hostname or "").lower().rstrip(".")
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(
                    "CORS_ORIGINS must use https:// and include a valid host"
                )
            has_extra_path = parsed.path not in ("", "/")
            has_extra_parts = parsed.query or parsed.params or parsed.fragment
            if has_extra_path or has_extra_parts:
                raise ValueError(
                    "CORS_ORIGINS entries must not include path/query/fragment"
                )
            if host in LOCAL_ALLOWED_HOSTS:
                raise ValueError("CORS_ORIGINS must not include localhost addresses")
            if not is_tailscale_hostname(host):
                raise ValueError("CORS_ORIGINS must use Tailscale (*.ts.net) origins")
            normalized.append(f"https://{host}")

        # 順序を維持して重複を除去
        deduplicated = list(dict.fromkeys(normalized))
        return ",".join(deduplicated)

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """環境変数から設定をロードします。

        Returns:
            設定済みのGatewayConfigインスタンス

        Raises:
            ValidationError: 必須の環境変数が不足している場合
        """
        config = cls()

        # ロギング設定
        logging.basicConfig(
            level=getattr(logging, config.log_level.upper()),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

        return config
