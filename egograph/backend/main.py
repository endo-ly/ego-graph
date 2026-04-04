"""EgoGraph Backend - FastAPI application entry point.

ハイブリッドBackend: LLMエージェント + 汎用データアクセスREST API
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend.api import (
    browser_history_data,
    chat,
    data,
    github,
    health,
    system_prompts,
    threads,
)
from backend.config import BackendConfig
from backend.infrastructure.database import ChatSQLiteConnection, create_chat_tables

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理。

    起動時にチャット履歴用のテーブルを作成します。
    """
    logger.info("Running startup tasks")
    try:
        with ChatSQLiteConnection() as conn:
            create_chat_tables(conn)
        logger.info("Chat tables initialized successfully")
    except Exception:
        logger.exception("Failed to initialize chat tables")
        raise

    yield


def create_app(config: BackendConfig | None = None) -> FastAPI:
    """FastAPIアプリケーションを作成します。

    Args:
        config: Backend設定（テスト用にオーバーライド可能）

    Returns:
        FastAPI: 設定済みのFastAPIアプリ
    """
    if config is None:
        config = BackendConfig.from_env()

    app = FastAPI(
        title="EgoGraph Backend API",
        description="Hybrid Backend: LLM Agent + Direct Data Access REST API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        GZipMiddleware,
        minimum_size=1000,
        compresslevel=6,
    )

    # CORS設定（環境変数から読み取り）
    origins = [
        origin.strip() for origin in config.cors_origins.split(",") if origin.strip()
    ]

    # ワイルドカードまたは空のオリジンリストの場合は警告を出力
    if "*" in origins:
        logger.warning(
            "CORS: ワイルドカード '*' が設定されています。開発環境用です。"
            "本番環境では具体的なオリジンを指定してください。"
        )
        origins = ["*"]
    elif not origins:
        logger.warning(
            "CORS origins が設定されていません。"
            "CORSミドルウェアは空のオリジンリストで動作します。"
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ルーターの登録
    app.include_router(health.router)
    app.include_router(data.router)
    app.include_router(browser_history_data.router)
    app.include_router(github.router)
    # YouTubeルーターは一時非推奨 (2025-02-04)
    # app.include_router(youtube.router)
    app.include_router(chat.router)
    app.include_router(threads.router)
    app.include_router(system_prompts.router)

    logger.info("EgoGraph Backend initialized successfully")

    return app


# モジュールレベルでのアプリインスタンス（プロダクション用）
app = create_app()


if __name__ == "__main__":
    import sys

    import uvicorn

    try:
        config = BackendConfig.from_env()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        logger.error(
            "Please check your .env file. Required settings:\n"
            "  - R2_ENDPOINT_URL\n"
            "  - R2_ACCESS_KEY_ID\n"
            "  - R2_SECRET_ACCESS_KEY\n"
            "  - R2_BUCKET_NAME\n"
            "Optional settings:\n"
            "  - LLM_PROVIDER\n"
            "  - LLM_API_KEY\n"
            "  - LLM_MODEL_NAME"
        )
        sys.exit(1)

    logger.info("Starting EgoGraph Backend on %s:%s", config.host, config.port)

    # reloadモードではimport stringを使う必要がある
    if config.reload:
        uvicorn.run(
            "backend.main:app",  # import string（モジュールレベルのappを使用）
            host=config.host,
            port=config.port,
            reload=True,
        )
    else:
        # 本番環境ではappインスタンスを直接渡す
        uvicorn.run(
            create_app(config),
            host=config.host,
            port=config.port,
            reload=False,
        )
