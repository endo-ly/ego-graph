"""FastAPI dependency functions.

設定の取得、DuckDB接続ファクトリなどの依存関数を提供します。
"""

import logging
from collections.abc import Generator

import duckdb
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from backend.config import BackendConfig, R2Config
from backend.infrastructure.database import DuckDBConnection
from backend.infrastructure.repositories.browser_history_repository import (
    BrowserHistoryRepository,
)
from backend.infrastructure.repositories.github_repository import GitHubRepository
from backend.infrastructure.repositories.spotify_repository import SpotifyRepository
from backend.infrastructure.repositories.youtube_repository import YouTubeRepository

logger = logging.getLogger(__name__)

# OpenAPIドキュメントにX-API-Key認証を表示するためのno-opセキュリティ依存。
# 実際の認証は _ApiKeyAuthMiddleware が行う。
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key_docs(api_key: str | None = Security(api_key_header)) -> None:
    """OpenAPIスキーマに認証要件を表示するためのno-op依存関数。

    実際のAPIキー検証は _ApiKeyAuthMiddleware で行うため、
    この関数は何も検証しない。/docs にセキュリティ定義を表示する目的のみ。
    """


# グローバル設定（1回だけロード）
_config: BackendConfig | None = None


def get_config() -> BackendConfig:
    """Backend設定を取得します。

    初回呼び出し時に環境変数から設定をロードし、キャッシュします。

    Returns:
        BackendConfig

    Raises:
        ValueError: 必須設定が不足している場合
    """
    global _config
    if _config is None:
        logger.info("Loading backend configuration")
        _config = BackendConfig.from_env()
    return _config


def get_db_connection(
    config: BackendConfig = Depends(get_config),
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """DuckDB接続を取得します（R2データレイク用）。

    DuckDBConnectionをコンテキストマネージャーとして使用し、
    開かれた接続をyieldします。接続は自動的にクローズされます。

    Args:
        config: Backend設定

    Yields:
        duckdb.DuckDBPyConnection: 開かれたDuckDB接続

    Raises:
        ValueError: R2設定が不足している場合
    """
    if not config.r2:
        raise ValueError("R2 configuration is required")

    with DuckDBConnection(config.r2) as conn:
        yield conn


def _require_r2(config: BackendConfig) -> R2Config:
    """R2設定が存在することを検証して返す。

    Args:
        config: Backend設定

    Returns:
        R2Config

    Raises:
        ValueError: R2設定が不足している場合
    """
    if not config.r2:
        raise ValueError("R2 configuration is required")
    return config.r2


def get_spotify_repository(
    config: BackendConfig = Depends(get_config),
) -> SpotifyRepository:
    return SpotifyRepository(_require_r2(config), tz=config.timezone)


def get_github_repository(
    config: BackendConfig = Depends(get_config),
) -> GitHubRepository:
    return GitHubRepository(_require_r2(config), tz=config.timezone)


def get_browser_history_repository(
    config: BackendConfig = Depends(get_config),
) -> BrowserHistoryRepository:
    return BrowserHistoryRepository(_require_r2(config), tz=config.timezone)


def get_youtube_repository(
    config: BackendConfig = Depends(get_config),
) -> YouTubeRepository:
    return YouTubeRepository(_require_r2(config), tz=config.timezone)
