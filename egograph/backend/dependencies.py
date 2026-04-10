"""FastAPI dependency functions.

設定の取得、DuckDB接続ファクトリ、認証などの依存関数を提供します。
"""

import logging
import secrets
from collections.abc import Generator

import duckdb
from fastapi import Depends, Header, HTTPException

from backend.config import BackendConfig
from backend.infrastructure.database import DuckDBConnection

logger = logging.getLogger(__name__)

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
async def verify_api_key(
    x_api_key: str | None = Header(None),
    config: BackendConfig = Depends(get_config),
) -> None:
    """API Key認証（オプショナル）。

    設定でBACKEND_API_KEYが指定されている場合のみ認証を行います。

    Args:
        x_api_key: X-API-Keyヘッダーの値
        config: Backend設定

    Raises:
        HTTPException: 認証に失敗した場合（401）
    """
    # API Keyが設定されていない場合は認証不要
    if config.api_key is None:
        return

    # API Keyが設定されている場合は検証（timing attack対策）
    if not x_api_key or not secrets.compare_digest(
        str(x_api_key), str(config.api_key.get_secret_value())
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")
