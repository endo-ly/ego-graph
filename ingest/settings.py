"""Ingest用の環境変数ローダー。"""

import logging
from collections.abc import Callable
from typing import TypeVar

from pydantic import AliasChoices, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from ingest.config import (
    Config,
    DuckDBConfig,
    EmbeddingConfig,
    GitHubWorklogConfig,
    GoogleActivityConfig,
    QdrantConfig,
    R2Config,
    SpotifyConfig,
    YouTubeConfig,
)

ENV_FILES = ["ingest/.env", ".env"]

T = TypeVar("T")


def _try_load_config(
    loader: Callable[[], T], name: str, *, required: bool = False
) -> T | None:
    """設定をロードし、失敗時はログを出力してNoneを返す。

    Args:
        loader: 設定をロードする関数
        name: ログ用の設定名
        required: True の場合、失敗時に例外を再送出

    Returns:
        ロードされた設定、または None
    """
    try:
        return loader()
    except (ValidationError, ValueError) as e:
        if required:
            raise
        logging.info("%s config not available: %s", name, type(e).__name__)
        return None


class SpotifySettings(BaseSettings):
    """Spotify API設定。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    client_id: str = Field(..., alias="SPOTIFY_CLIENT_ID")
    client_secret: SecretStr = Field(..., alias="SPOTIFY_CLIENT_SECRET")
    refresh_token: SecretStr = Field(..., alias="SPOTIFY_REFRESH_TOKEN")
    redirect_uri: str = Field(
        "http://127.0.0.1:8888/callback", alias="SPOTIFY_REDIRECT_URI"
    )
    scope: str = Field(
        "user-read-recently-played playlist-read-private playlist-read-collaborative",
        alias="SPOTIFY_SCOPE",
    )

    def to_config(self) -> SpotifyConfig:
        return SpotifyConfig(
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.refresh_token,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
        )


class GitHubWorklogSettings(BaseSettings):
    """GitHub作業ログ取り込み設定。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    token: SecretStr = Field(
        ...,
        validation_alias=AliasChoices("GITHUB_PAT", "GITHUB_TOKEN"),
    )
    github_login: str = Field(..., alias="GITHUB_LOGIN")
    target_repos: list[str] | None = Field(None, alias="GITHUB_TARGET_REPOS")
    backfill_days: int = Field(365, alias="GITHUB_BACKFILL_DAYS")
    fetch_commit_details: bool = Field(True, alias="GITHUB_FETCH_COMMIT_DETAILS")
    max_commit_detail_requests_per_repo: int = Field(
        200,
        alias="GITHUB_MAX_COMMIT_DETAIL_REQUESTS_PER_REPO",
    )

    def to_config(self) -> GitHubWorklogConfig:
        return GitHubWorklogConfig(
            token=self.token,
            github_login=self.github_login,
            target_repos=self.target_repos,
            backfill_days=self.backfill_days,
            fetch_commit_details=self.fetch_commit_details,
            max_commit_detail_requests_per_repo=self.max_commit_detail_requests_per_repo,
        )


class EmbeddingSettings(BaseSettings):
    """埋め込みモデル設定(ローカル実行)。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    model_name: str = Field("cl-nagoya/ruri-v3-310m", alias="EMBEDDING_MODEL_NAME")
    batch_size: int = Field(32, alias="EMBEDDING_BATCH_SIZE")
    device: str | None = Field(None, alias="EMBEDDING_DEVICE")
    expected_dimension: int = Field(768, alias="EMBEDDING_DIMENSION")

    def to_config(self) -> EmbeddingConfig:
        return EmbeddingConfig(
            model_name=self.model_name,
            batch_size=self.batch_size,
            device=self.device,
            expected_dimension=self.expected_dimension,
        )


class GoogleActivitySettings(BaseSettings):
    """Google Activity API設定。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    accounts: list[str] = Field(default_factory=list, alias="GOOGLE_ACTIVITY_ACCOUNTS")

    def to_config(self) -> GoogleActivityConfig:
        if not self.accounts:
            raise ValueError("GOOGLE_ACTIVITY_ACCOUNTS is required but not set")
        return GoogleActivityConfig(accounts=self.accounts)


class YouTubeSettings(BaseSettings):
    """YouTube API設定。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    youtube_api_key: SecretStr = Field(..., alias="YOUTUBE_API_KEY")

    def to_config(self) -> YouTubeConfig:
        return YouTubeConfig(youtube_api_key=self.youtube_api_key)


class QdrantSettings(BaseSettings):
    """Qdrant Cloud設定。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    url: str = Field(..., alias="QDRANT_URL")
    api_key: SecretStr = Field(..., alias="QDRANT_API_KEY")
    collection_name: str = Field(
        "egograph_spotify_ruri", alias="QDRANT_COLLECTION_NAME"
    )
    vector_size: int = Field(768, alias="QDRANT_VECTOR_SIZE")
    batch_size: int = Field(1000, alias="QDRANT_BATCH_SIZE")

    def to_config(self) -> QdrantConfig:
        return QdrantConfig(
            url=self.url,
            api_key=self.api_key,
            collection_name=self.collection_name,
            vector_size=self.vector_size,
            batch_size=self.batch_size,
        )


class R2Settings(BaseSettings):
    """Cloudflare R2設定 (S3互換)。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    endpoint_url: str = Field(..., alias="R2_ENDPOINT_URL")
    access_key_id: str = Field(..., alias="R2_ACCESS_KEY_ID")
    secret_access_key: SecretStr = Field(..., alias="R2_SECRET_ACCESS_KEY")
    bucket_name: str = Field("egograph", alias="R2_BUCKET_NAME")
    raw_path: str = Field("raw/", alias="R2_RAW_PATH")
    events_path: str = Field("events/", alias="R2_EVENTS_PATH")
    master_path: str = Field("master/", alias="R2_MASTER_PATH")

    def to_config(self) -> R2Config:
        return R2Config(
            endpoint_url=self.endpoint_url,
            access_key_id=self.access_key_id,
            secret_access_key=self.secret_access_key,
            bucket_name=self.bucket_name,
            raw_path=self.raw_path,
            events_path=self.events_path,
            master_path=self.master_path,
        )


class DuckDBSettings(BaseSettings):
    """DuckDB設定。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    db_path: str = Field("data/analytics.duckdb", alias="DUCKDB_PATH")

    def to_config(self, r2_config: R2Config | None) -> DuckDBConfig:
        return DuckDBConfig(db_path=self.db_path, r2=r2_config)


class IngestSettings(BaseSettings):
    """Ingest設定。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore"
    )

    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @classmethod
    def load(cls) -> Config:
        """環境変数から共有Configを構築する。"""
        settings = cls()
        config = Config(log_level=settings.log_level)

        config.spotify = _try_load_config(
            lambda: SpotifySettings().to_config(), "Spotify"
        )
        config.google_activity = _try_load_config(
            lambda: GoogleActivitySettings().to_config(), "GoogleActivity"
        )
        config.youtube = _try_load_config(
            lambda: YouTubeSettings().to_config(), "YouTube"
        )
        config.github_worklog = _try_load_config(
            lambda: GitHubWorklogSettings().to_config(), "GitHubWorklog"
        )
        config.embedding = _try_load_config(
            lambda: EmbeddingSettings().to_config(), "Embedding"
        )
        config.qdrant = _try_load_config(lambda: QdrantSettings().to_config(), "Qdrant")

        r2_config = _try_load_config(lambda: R2Settings().to_config(), "R2")
        config.duckdb = _try_load_config(
            lambda: DuckDBSettings().to_config(r2_config), "DuckDB"
        )

        logging.basicConfig(
            level=getattr(logging, config.log_level.upper()),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            force=True,  # 既存のハンドラを強制的に上書き
        )

        return config
