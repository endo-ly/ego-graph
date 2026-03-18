"""Health check endpoint."""

import logging

from fastapi import APIRouter, Depends

from backend.config import BackendConfig
from backend.constants import HEALTH_CHECK_LIMIT
from backend.dependencies import get_config, get_db_connection
from backend.infrastructure.database import DuckDBConnection, build_dataset_glob

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


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

        return {
            "status": "ok",
            "duckdb": "connected",
            "r2": "accessible",
            "data_available": data_exists,
        }

    except FileNotFoundError as e:
        logger.warning("Health check local parquet not found: %s", e)
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.exception("Health check failed")
        return {"status": "error", "error": str(e)}
