"""Pipelines サービス設定。"""

import os
from pathlib import Path

from egograph_paths import PIPELINES_LOGS_DIR, PIPELINES_STATE_DB_PATH
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

USE_ENV_FILE = os.getenv("USE_ENV_FILE", "true").lower() in ("true", "1", "yes")
PIPELINES_ENV_FILES = ["egograph/pipelines/.env"] if USE_ENV_FILE else []


class PipelinesConfig(BaseSettings):
    """pipelines サービスの実行設定。"""

    model_config = SettingsConfigDict(
        env_file=PIPELINES_ENV_FILES,
        env_file_encoding="utf-8",
        env_prefix="PIPELINES_",
        extra="ignore",
        populate_by_name=True,
    )

    database_path: Path = PIPELINES_STATE_DB_PATH
    logs_root: Path = PIPELINES_LOGS_DIR
    host: str = "127.0.0.1"
    port: int = 8001
    api_key: SecretStr | None = None
    timezone: str = "UTC"
    dispatcher_poll_seconds: float = 1.0
    max_concurrent_runs: int = 4
    lock_lease_seconds: int = 300
    lock_heartbeat_seconds: int = 30
    webhook_url: str | None = None
    webhook_type: str = "generic"
    google_health_client_id: SecretStr | None = Field(
        None,
        validation_alias="GOOGLE_HEALTH_CLIENT_ID",
    )
    google_health_client_secret: SecretStr | None = Field(
        None,
        validation_alias="GOOGLE_HEALTH_CLIENT_SECRET",
    )
    google_health_redirect_uri: str | None = Field(
        None,
        validation_alias="GOOGLE_HEALTH_REDIRECT_URI",
    )
    google_health_token_encryption_key: SecretStr | None = Field(
        None,
        validation_alias="GOOGLE_HEALTH_TOKEN_ENCRYPTION_KEY",
    )

    @property
    def google_health_is_configured(self) -> bool:
        """Google Health OAuth 設定がすべて揃っているか返す。"""
        return all(
            (
                self.google_health_client_id,
                self.google_health_client_secret,
                self.google_health_redirect_uri,
                self.google_health_token_encryption_key,
            )
        )
