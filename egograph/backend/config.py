"""EgoGraph Backend設定管理。"""

import logging
import os

from egograph_paths import PARQUET_DATA_DIR
from pydantic import BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# 環境変数で .env ファイルの使用を制御（デフォルトは使用）
USE_ENV_FILE = os.getenv("USE_ENV_FILE", "true").lower() in ("true", "1", "yes")
BACKEND_ENV_FILES = ["egograph/backend/.env"] if USE_ENV_FILE else []


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
        env_file=BACKEND_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # サーバー設定
    host: str = Field("127.0.0.1", alias="BACKEND_HOST")
    port: int = Field(8000, alias="BACKEND_PORT")
    reload: bool = Field(True, alias="BACKEND_RELOAD")

    # オプショナル認証
    api_key: SecretStr | None = Field(None, alias="BACKEND_API_KEY")

    # CORS設定
    cors_origins: str = Field("*", alias="CORS_ORIGINS")  # カンマ区切り

    # ロギング
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # サブ設定
    r2: R2Config | None = None

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
        if not self.api_key:
            raise ValueError("BACKEND_API_KEY is required for production")
        if self.cors_origins == "*":
            raise ValueError(
                "CORS_ORIGINS must be explicitly configured for production (not '*')"
            )


class R2Settings(BaseSettings):
    """Cloudflare R2設定 (S3互換)。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILES,
        env_file_encoding="utf-8",
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
