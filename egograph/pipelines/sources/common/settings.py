"""Environment variable settings loader for pipelines sources."""

import logging
import os
from collections.abc import Callable
from typing import TypeVar

from pydantic import AliasChoices, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from pipelines.sources.common.config import (
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

T = TypeVar("T")

USE_ENV_FILE = os.getenv("USE_ENV_FILE", "true").lower() in ("true", "1", "yes")
PIPELINES_ENV_FILES = ["egograph/pipelines/.env"] if USE_ENV_FILE else []


def _try_load_config(
    loader: Callable[[], T],
    name: str,
    *,
    required: bool = False,
) -> T | None:
    """設定を読み込み、任意設定なら欠落時 None を返す。"""
    try:
        return loader()
    except (ValidationError, ValueError) as exc:
        if required:
            raise
        logging.info("%s config not available: %s", name, type(exc).__name__)
        return None


class _RuntimeBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PIPELINES_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class SpotifySettings(_RuntimeBaseSettings):
    """Spotify API設定。"""

    client_id: str = Field(..., alias="SPOTIFY_CLIENT_ID")
    client_secret: SecretStr = Field(..., alias="SPOTIFY_CLIENT_SECRET")
    refresh_token: SecretStr = Field(..., alias="SPOTIFY_REFRESH_TOKEN")
    redirect_uri: str = "http://127.0.0.1:8888/callback"
    scope: str = (
        "user-read-recently-played playlist-read-private playlist-read-collaborative"
    )

    def to_config(self) -> SpotifyConfig:
        return SpotifyConfig(
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.refresh_token,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
        )


class GitHubWorklogSettings(_RuntimeBaseSettings):
    """GitHub作業ログ設定。"""

    token: SecretStr = Field(
        ...,
        validation_alias=AliasChoices("GITHUB_PAT", "GITHUB_TOKEN"),
    )
    github_login: str = Field(..., alias="GITHUB_LOGIN")
    target_repos: list[str] | None = Field(None, alias="GITHUB_TARGET_REPOS")
    backfill_days: int = 365
    fetch_commit_details: bool = True
    max_commit_detail_requests_per_repo: int = 200

    def to_config(self) -> GitHubWorklogConfig:
        return GitHubWorklogConfig(
            token=self.token,
            github_login=self.github_login,
            target_repos=self.target_repos,
            backfill_days=self.backfill_days,
            fetch_commit_details=self.fetch_commit_details,
            max_commit_detail_requests_per_repo=(
                self.max_commit_detail_requests_per_repo
            ),
        )


class GoogleActivitySettings(_RuntimeBaseSettings):
    """Google Activity 設定。"""

    accounts: list[str] = Field(default_factory=list, alias="GOOGLE_ACTIVITY_ACCOUNTS")

    def to_config(self) -> GoogleActivityConfig:
        if not self.accounts:
            raise ValueError("GOOGLE_ACTIVITY_ACCOUNTS is required but not set")
        return GoogleActivityConfig(accounts=self.accounts)


class YouTubeSettings(_RuntimeBaseSettings):
    """YouTube API設定。"""

    youtube_api_key: SecretStr = Field(..., alias="YOUTUBE_API_KEY")

    def to_config(self) -> YouTubeConfig:
        return YouTubeConfig(youtube_api_key=self.youtube_api_key)


class EmbeddingSettings(_RuntimeBaseSettings):
    """埋め込みモデル設定。"""

    model_name: str = "cl-nagoya/ruri-v3-310m"
    batch_size: int = 32
    device: str | None = None
    expected_dimension: int = 768

    def to_config(self) -> EmbeddingConfig:
        return EmbeddingConfig(
            model_name=self.model_name,
            batch_size=self.batch_size,
            device=self.device,
            expected_dimension=self.expected_dimension,
        )


class QdrantSettings(_RuntimeBaseSettings):
    """Qdrant 設定。"""

    url: str = Field(..., alias="QDRANT_URL")
    api_key: SecretStr = Field(..., alias="QDRANT_API_KEY")
    collection_name: str = "egograph_spotify_ruri"
    vector_size: int = 768
    batch_size: int = 1000

    def to_config(self) -> QdrantConfig:
        return QdrantConfig(
            url=self.url,
            api_key=self.api_key,
            collection_name=self.collection_name,
            vector_size=self.vector_size,
            batch_size=self.batch_size,
        )


class R2Settings(_RuntimeBaseSettings):
    """Cloudflare R2設定。"""

    endpoint_url: str = Field(..., alias="R2_ENDPOINT_URL")
    access_key_id: str = Field(..., alias="R2_ACCESS_KEY_ID")
    secret_access_key: SecretStr = Field(..., alias="R2_SECRET_ACCESS_KEY")
    bucket_name: str = Field("egograph", alias="R2_BUCKET_NAME")
    raw_path: str = "raw/"
    events_path: str = "events/"
    master_path: str = "master/"
    local_parquet_root: str | None = Field(
        "data/parquet",
        alias="LOCAL_PARQUET_ROOT",
    )

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


class DuckDBSettings(_RuntimeBaseSettings):
    """DuckDB設定。"""

    db_path: str = "data/analytics.duckdb"

    def to_config(self, r2_config: R2Config | None) -> DuckDBConfig:
        return DuckDBConfig(db_path=self.db_path, r2=r2_config)


class PipelinesSettings(_RuntimeBaseSettings):
    """Pipelines source runtime 設定。"""

    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @classmethod
    def load(cls) -> Config:
        """プロセス環境変数から Config を組み立てる。"""
        settings = cls()
        config = Config(log_level=settings.log_level)
        config.spotify = _try_load_config(
            lambda: SpotifySettings().to_config(),
            "Spotify",
        )
        config.google_activity = _try_load_config(
            lambda: GoogleActivitySettings().to_config(),
            "GoogleActivity",
        )
        config.youtube = _try_load_config(
            lambda: YouTubeSettings().to_config(),
            "YouTube",
        )
        config.github_worklog = _try_load_config(
            lambda: GitHubWorklogSettings().to_config(),
            "GitHubWorklog",
        )
        config.embedding = _try_load_config(
            lambda: EmbeddingSettings().to_config(),
            "Embedding",
        )
        config.qdrant = _try_load_config(
            lambda: QdrantSettings().to_config(),
            "Qdrant",
        )
        r2_config = _try_load_config(lambda: R2Settings().to_config(), "R2")
        config.duckdb = _try_load_config(
            lambda: DuckDBSettings().to_config(r2_config),
            "DuckDB",
        )
        logging.basicConfig(
            level=getattr(logging, config.log_level.upper()),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            force=True,
        )
        return config
