"""EgoGraph Backend設定管理。

LLM APIとバックエンドサーバー固有の設定を追加します。
"""

import logging
import os

from pydantic import BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# 環境変数で .env ファイルの使用を制御（デフォルトは使用）
USE_ENV_FILE = os.getenv("USE_ENV_FILE", "true").lower() in ("true", "1", "yes")
BACKEND_ENV_FILES = ["backend/.env"] if USE_ENV_FILE else []


class R2Config(BaseModel):
    """Cloudflare R2設定 (S3互換)。"""

    endpoint_url: str
    access_key_id: str
    secret_access_key: SecretStr
    bucket_name: str = "egograph"
    raw_path: str = "raw/"
    events_path: str = "events/"
    master_path: str = "master/"
    local_parquet_root: str | None = None


PROVIDERS_CONFIG = {
    "openai": {
        "api_key_field": "openai_api_key",
        "env_var": "OPENAI_API_KEY",
    },
    "anthropic": {
        "api_key_field": "anthropic_api_key",
        "env_var": "ANTHROPIC_API_KEY",
    },
    "openrouter": {
        "api_key_field": "openrouter_api_key",
        "env_var": "OPENROUTER_API_KEY",
    },
}


class LLMConfig(BaseSettings):
    """LLM API設定。

    複数プロバイダーに対応し、プロバイダーごとのAPIキーを管理します。
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # プロバイダーごとのAPIキー
    openai_api_key: SecretStr | None = Field(None, alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(None, alias="ANTHROPIC_API_KEY")
    openrouter_api_key: SecretStr | None = Field(None, alias="OPENROUTER_API_KEY")

    # デフォルトモデル（未指定時のフォールバック）
    default_model: str = Field("deepseek/deepseek-v3.2", alias="DEFAULT_LLM_MODEL")

    # 生成パラメータ
    temperature: float = Field(0.7, alias="LLM_TEMPERATURE")
    max_tokens: int = Field(2048, alias="LLM_MAX_TOKENS")

    # OpenRouter固有の設定
    enable_web_search: bool = Field(
        False, alias="LLM_ENABLE_WEB_SEARCH"
    )  # デフォルトはオフ

    def get_api_key(self, provider: str) -> str:
        """プロバイダーに対応するAPIキーを取得します。

        Args:
            provider: プロバイダー名（"openai", "anthropic", "openrouter"）

        Returns:
            プロバイダーに対応するAPIキー（文字列）

        Raises:
            ValueError: 対応プロバイダーのAPIキーが未設定の場合
            ValueError: サポート対象外のプロバイダー名が指定された場合

        Example:
            >>> config = LLMConfig.model_construct(openai_api_key=SecretStr("sk-test"))
            >>> config.get_api_key("openai")
            'sk-test'
        """
        provider_lower = provider.lower()
        provider_config = PROVIDERS_CONFIG.get(provider_lower)

        if not provider_config:
            supported = ", ".join(PROVIDERS_CONFIG.keys())
            raise ValueError(
                f"Unsupported provider: {provider}. Supported: {supported}"
            )

        api_key = getattr(self, provider_config["api_key_field"])
        if not api_key or not api_key.get_secret_value():
            raise ValueError(
                f"{provider_config['env_var']} is not set. "
                "Please set the environment variable."
            )
        return api_key.get_secret_value()


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
    llm: LLMConfig | None = None
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

        # LLM設定のロード
        try:
            config.llm = LLMConfig()
        except (ValidationError, ValueError):
            logging.warning(
                "LLM config not available. Chat endpoints will be disabled."
            )

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
        if not self.llm:
            raise ValueError("LLM configuration is required for production")
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
    local_parquet_root: str | None = Field(None, alias="LOCAL_PARQUET_ROOT")

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
