"""FastAPI dependency functions.

設定の取得、DuckDB接続ファクトリなどの依存関数を提供します。
"""

import logging
from collections.abc import Generator

import duckdb
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from backend.config import BackendConfig, R2Config
from backend.domain.tools.timeline.daily import (
    GetDailyTimelineTool,
    resolve_default_timezone,
)
from backend.infrastructure.database import DuckDBConnection
from backend.infrastructure.repositories.browser_history_repository import (
    BrowserHistoryRepository,
)
from backend.infrastructure.repositories.github_repository import GitHubRepository
from backend.infrastructure.repositories.google_health_repository import (
    GoogleHealthRepository,
)
from backend.infrastructure.repositories.spotify_repository import SpotifyRepository
from backend.infrastructure.repositories.timeline_repository import (
    TimelineRepository,
)
from backend.infrastructure.repositories.youtube_repository import YouTubeRepository
from backend.usecases.google_health import (
    GetGoogleHealthDailyMetricsUseCase,
    GetGoogleHealthDailySummaryUseCase,
    GetGoogleHealthRecordUseCase,
    GetGoogleHealthSessionsUseCase,
    GetGoogleHealthTimeseriesUseCase,
)

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
        raise ValueError("invalid_r2_config: R2 configuration is required")

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
        raise ValueError("invalid_r2_config: R2 configuration is required")
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


def get_google_health_repository(
    config: BackendConfig = Depends(get_config),
) -> GoogleHealthRepository:
    try:
        r2_config = _require_r2(config)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return GoogleHealthRepository(r2_config, tz=config.timezone)


def get_google_health_daily_summary_use_case(
    repository: GoogleHealthRepository = Depends(get_google_health_repository),
) -> GetGoogleHealthDailySummaryUseCase:
    """Google Health日次サマリ取得UseCaseを構築する。"""
    return GetGoogleHealthDailySummaryUseCase(repository)


def get_google_health_daily_metrics_use_case(
    repository: GoogleHealthRepository = Depends(get_google_health_repository),
) -> GetGoogleHealthDailyMetricsUseCase:
    """Google Health日次Projection取得UseCaseを構築する。"""
    return GetGoogleHealthDailyMetricsUseCase(repository)


def get_google_health_timeseries_use_case(
    config: BackendConfig = Depends(get_config),
    repository: GoogleHealthRepository = Depends(get_google_health_repository),
) -> GetGoogleHealthTimeseriesUseCase:
    """Google Health時系列取得UseCaseを構築する。"""
    return GetGoogleHealthTimeseriesUseCase(repository, timezone=config.timezone)


def get_google_health_sessions_use_case(
    repository: GoogleHealthRepository = Depends(get_google_health_repository),
) -> GetGoogleHealthSessionsUseCase:
    """Google Health session取得UseCaseを構築する。"""
    return GetGoogleHealthSessionsUseCase(repository)


def get_google_health_record_use_case(
    repository: GoogleHealthRepository = Depends(get_google_health_repository),
) -> GetGoogleHealthRecordUseCase:
    """Google Health完全保存record取得UseCaseを構築する。"""
    return GetGoogleHealthRecordUseCase(repository)


def get_timeline_repository(
    config: BackendConfig = Depends(get_config),
) -> TimelineRepository:
    try:
        r2 = _require_r2(config)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid_r2_config: {exc}",
        ) from exc
    return TimelineRepository(r2)


def get_daily_timeline_tool(
    config: BackendConfig = Depends(get_config),
    repository: TimelineRepository = Depends(get_timeline_repository),
) -> GetDailyTimelineTool:
    """Daily Timeline MCP ツールを構築する。"""
    return GetDailyTimelineTool(
        repository,
        default_timezone=resolve_default_timezone(
            config.timezone,
            timezone_configured=config.timezone_configured,
        ),
    )
