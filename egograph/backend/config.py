"""EgoGraph Backend設定管理。"""

import logging
import os
from typing import Literal
from zoneinfo import ZoneInfo

from egograph_paths import PARQUET_DATA_DIR
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class R2Config(BaseModel):
    """Cloudflare R2設定 (S3互換)。"""

    endpoint_url: str
    access_key_id: str
    secret_access_key: SecretStr
    bucket_name: str = "egograph"
    raw_path: str = "raw/"
    events_path: str = "events/"
    master_path: str = "master/"
    local_parquet_root: str | None = str(PARQUET_DATA_DIR)


class BackendConfig(BaseSettings):
    """Backend APIサーバー設定。"""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
    )

    # サーバー設定
    host: str = Field("127.0.0.1", alias="BACKEND_HOST")
    port: int = Field(8000, alias="BACKEND_PORT")
    reload: bool = Field(True, alias="BACKEND_RELOAD")
    environment: Literal["development", "production"] = Field(
        "development", alias="BACKEND_ENV"
    )

    # オプショナル認証
    api_key: SecretStr | None = Field(None, alias="BACKEND_API_KEY")

    # CORS設定
    cors_origins: str = Field("", alias="CORS_ORIGINS")  # カンマ区切り。空で無効

    # ロギング
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # タイムゾーン（クエリ時の日付解釈に使用。保存は常にUTC）
    timezone: ZoneInfo = Field(ZoneInfo("UTC"), alias="TIMEZONE")

    @field_validator("timezone", mode="before")
    @classmethod
    def _parse_timezone(cls, v: str | ZoneInfo) -> ZoneInfo:
        """タイムゾーン文字列をZoneInfoに変換する。"""
        if isinstance(v, ZoneInfo):
            return v
        return ZoneInfo(v)

    # サブ設定
    r2: R2Config | None = None

    @property
    def timezone_configured(self) -> bool:
        """TIMEZONE が明示設定されているかを返す。"""
        return "timezone" in self.model_fields_set or "TIMEZONE" in os.environ

    # MCP transport security: テスト環境向けにHost許可リストを設定可能
    mcp_allowed_hosts: list[str] = Field([], alias="MCP_ALLOWED_HOSTS")

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """環境変数から設定をロードします。

        Returns:
            設定済みのBackendConfigインスタンス

        Raises:
            ValueError: 必須の環境変数が不足している場合
        """
        config = cls()

        # R2設定のロード
        try:
            config.r2 = R2Settings().to_config()
        except (ValidationError, ValueError) as e:
            logging.exception("R2 config is required for backend operation")
            raise ValueError(
                "R2 configuration is missing. Please set R2_* env vars."
            ) from e

        # ロギング設定
        logging.basicConfig(
            level=getattr(logging, config.log_level.upper()),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

        return config

    def validate_for_production(self) -> None:
        """本番環境用の設定を検証します。

        Raises:
            ValueError: 本番環境で必須の設定が不足している場合
        """
        if self.api_key is None or not self.api_key.get_secret_value().strip():
            raise ValueError("BACKEND_API_KEY is required for production")
        if self.cors_origins.strip():
            origins = [origin.strip() for origin in self.cors_origins.split(",")]
            if any(not origin or origin == "*" for origin in origins):
                raise ValueError(
                    "CORS_ORIGINS must contain non-empty origins (or be omitted) "
                    "and must not contain '*'"
                )
        if self.r2 is None:
            raise ValueError("R2 configuration is required for production")

    @property
    def mcp_transport_security(self):
        """MCP transport security設定を返す。

        テスト環境では許可リスト経由でtestserver等を許可する。
        本番環境ではDNS rebinding保護を無効化する（Tailscaleネットワーク内で
        WireGuard暗号化・認証済みのため、追加の保護は不要）。
        """
        if self.mcp_allowed_hosts:
            return TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=self.mcp_allowed_hosts,
                allowed_origins=self.mcp_allowed_hosts,
            )
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )


class R2Settings(BaseSettings):
    """Cloudflare R2設定 (S3互換)。"""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
    )

    endpoint_url: str = Field(..., alias="R2_ENDPOINT_URL")
    access_key_id: str = Field(..., alias="R2_ACCESS_KEY_ID")
    secret_access_key: SecretStr = Field(..., alias="R2_SECRET_ACCESS_KEY")
    bucket_name: str = Field("egograph", alias="R2_BUCKET_NAME")
    raw_path: str = Field("raw/", alias="R2_RAW_PATH")
    events_path: str = Field("events/", alias="R2_EVENTS_PATH")
    master_path: str = Field("master/", alias="R2_MASTER_PATH")
    local_parquet_root: str | None = str(PARQUET_DATA_DIR)

    def to_config(self) -> R2Config:
        return R2Config(
            endpoint_url=self.endpoint_url,
            access_key_id=self.access_key_id,
            secret_access_key=self.secret_access_key,
            bucket_name=self.bucket_name,
            raw_path=self.raw_path,
            events_path=self.events_path,
            master_path=self.master_path,
            local_parquet_root=self.local_parquet_root,
        )
