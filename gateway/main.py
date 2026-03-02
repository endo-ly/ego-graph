"""Gateway アプリケーションエントリポイント。

Starlette アプリケーションのセットアップとサーバー起動を行います。
"""

import logging
from urllib.parse import urlparse

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from gateway.api.push import routes as push_routes
from gateway.api.terminal import get_terminal_routes
from gateway.config import LOCAL_ALLOWED_HOSTS, is_tailscale_hostname
from gateway.dependencies import get_config
from gateway.infrastructure.database import init_database

logger = logging.getLogger(__name__)


def _parse_cors_origins(cors_origins: str) -> list[str]:
    """CORS_ORIGINS 文字列を配列に変換する。"""
    if not cors_origins.strip():
        return []
    return [origin.strip() for origin in cors_origins.split(",") if origin.strip()]


def _build_allowed_hosts(cors_origins: list[str]) -> list[str]:
    """TrustedHost 用のホスト許可リストを構築する。"""
    allowed_hosts = list(LOCAL_ALLOWED_HOSTS)
    for origin in cors_origins:
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host and is_tailscale_hostname(host):
            allowed_hosts.append(host)
    return list(dict.fromkeys(allowed_hosts))


def create_app() -> Starlette:
    """Gateway アプリケーションを作成します。

    Returns:
        設定済みの Starlette アプリケーション
    """
    config = get_config()

    # CORS ミドルウェアの設定
    cors_origins = _parse_cors_origins(config.cors_origins)
    if not cors_origins:
        logger.warning(
            "CORS_ORIGINS is empty; cross-origin browser access is disabled and "
            "TrustedHostMiddleware will restrict remote access to local hosts only"
        )
    allowed_hosts = _build_allowed_hosts(cors_origins)
    middleware = [
        Middleware(
            TrustedHostMiddleware,
            allowed_hosts=allowed_hosts,
        ),
        Middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    # データベース初期化
    try:
        init_database()
        logger.info("Database initialized")
    except Exception as e:
        logger.exception("Failed to initialize database: %s", e)
        raise

    # ルート設定
    routes = [
        # ヘルスチェック
        Route("/health", health_check, methods=["GET"]),
        # Push API
        *push_routes,
        # Terminal API
        Mount("/api", routes=get_terminal_routes()),
    ]

    app = Starlette(
        debug=config.log_level.upper() == "DEBUG",
        routes=routes,
        middleware=middleware,
    )

    logger.info("Gateway application created")
    return app


async def health_check(request) -> JSONResponse:
    """ヘルスチェックエンドポイント。

    Args:
        request: Starlette リクエストオブジェクト

    Returns:
        ヘルスステータスを含む辞書
    """
    return JSONResponse({"status": "healthy", "service": "gateway"})


def main() -> None:
    """サーバーを起動します。

    この関数は `uvicorn gateway.main:app` で起動するためのエントリポイントです。
    """
    config = get_config()

    uvicorn.run(
        "gateway.main:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
        reload_dirs=["gateway"] if config.reload else None,
        log_level=config.log_level.lower(),
    )


# アプリケーションインスタンス（uvicorn 起動用）
app = create_app()


if __name__ == "__main__":
    main()
