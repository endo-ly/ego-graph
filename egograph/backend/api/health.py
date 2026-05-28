"""Health check endpoint."""

import logging

import duckdb
from fastapi import APIRouter, Depends

from backend.config import BackendConfig
from backend.constants import HEALTH_CHECK_LIMIT
from backend.dependencies import get_config, get_db_connection
from backend.infrastructure.database import DuckDBConnection, build_dataset_glob
from backend.infrastructure.logging.sanitizers import sanitize_infra_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _build_health_response(*, data_available: bool) -> dict[str, str | bool]:
    """ヘルスチェックの標準レスポンスを構築する。"""
    return {
        "status": "ok",
        "duckdb": "connected",
        "r2": "accessible",
        "data_available": data_available,
    }


def _is_empty_dataset_error(error: Exception) -> bool:
    """初回投入前の空データ状態かどうかを判定する。"""
    if isinstance(error, FileNotFoundError):
        return True

    return isinstance(error, duckdb.IOException) and "No files found" in str(error)


@router.get("/health")
@router.get("/v1/health")
async def health_check(
    db_connection: DuckDBConnection = Depends(get_db_connection),
    config: BackendConfig = Depends(get_config),
):
    """ヘルスチェックエンドポイント。

    DuckDB + R2接続を確認し、システムの状態を返します。

    Returns:
        dict: システム状態

    Example Response:
        {
            "status": "ok",
            "duckdb": "connected",
            "r2": "accessible",
            "data_available": true
        }
    """
    try:
        # DuckDB + R2接続のテスト（軽量なクエリで確認）
        parquet_path = build_dataset_glob(
            config.r2,
            data_domain="events",
            dataset_path="spotify/plays",
        )

        with db_connection as conn:
            # COUNT(*)の代わりにLIMIT 1で存在確認のみ実施（高速）
            result = conn.execute(
                "SELECT 1 FROM read_parquet(?) LIMIT ?",
                [parquet_path, HEALTH_CHECK_LIMIT],
            ).fetchone()
            # データが存在するか確認
            data_exists = result is not None

        return _build_health_response(data_available=data_exists)
    except Exception as e:
        if _is_empty_dataset_error(e):
            logger.info("Health check found no compacted parquet yet: %s", e)
            return _build_health_response(data_available=False)

        logger.exception("Health check failed")
        return {"status": "error", "error": sanitize_infra_message(str(e))}
