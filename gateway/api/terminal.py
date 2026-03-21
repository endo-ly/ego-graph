"""Terminal API ルート。

tmux セッション一覧の取得などを提供します。
"""

import asyncio
import json
import logging
import re
from urllib.parse import urlparse

import anyio
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from gateway.config import (
    LOCAL_ALLOWED_HOSTS,
    is_allowed_client_ip,
    is_tailscale_hostname,
)
from gateway.dependencies import get_config, verify_gateway_token
from gateway.domain.models import SessionStatus, TerminalSnapshotResponse
from gateway.infrastructure.tmux import (
    get_active_pane_metadata,
    list_sessions,
    session_exists,
)
from gateway.services.pty_manager import TmuxAttachManager
from gateway.services.websocket_handler import TerminalWebSocketHandler
from gateway.services.ws_token_store import terminal_ws_token_store

logger = logging.getLogger(__name__)

AUTH_TIMEOUT_SECONDS = 10
WEBVIEW_ALLOWED_ORIGINS = {"null", "file://", "file:///"}


async def get_sessions(request: Request) -> JSONResponse:
    """tmux セッション一覧を取得します。

    `tmux list-sessions` を使用してセッション情報を取得し、
    `^agent-[0-9]{4}$` パターンに一致するセッションのみを返します。

    Args:
        request: Starlette リクエストオブジェクト

    Returns:
        セッション一覧を含む JSONResponse

    Raises:
        HTTPException: tmux コマンドが失敗した場合
    """
    await verify_gateway_token(request)

    try:
        tmux_sessions = await anyio.to_thread.run_sync(list_sessions)
    except OSError as e:
        logger.error("Failed to list tmux sessions: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list sessions") from e
    except Exception as e:
        logger.exception("Unexpected error listing sessions")
        raise HTTPException(status_code=500, detail="Unexpected error") from e

    # セッション情報を API レスポンス形式に変換
    sessions = [
        await _build_session_response(session.name, session)
        for session in tmux_sessions
    ]

    return JSONResponse(
        {
            "sessions": sessions,
            "count": len(sessions),
        }
    )


async def get_session(request: Request) -> JSONResponse:
    """指定された tmux セッション情報を取得します。"""
    await verify_gateway_token(request)

    session_id = request.path_params.get("session_id")
    if not session_id or not _validate_session_id(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    try:
        tmux_sessions = await anyio.to_thread.run_sync(list_sessions)
    except OSError as e:
        logger.error("Failed to list tmux sessions: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list sessions") from e
    except Exception as e:
        logger.exception("Unexpected error listing sessions")
        raise HTTPException(status_code=500, detail="Unexpected error") from e

    target = next(
        (session for session in tmux_sessions if session.name == session_id), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return JSONResponse(await _build_session_response(session_id, target))


async def issue_ws_token(request: Request) -> JSONResponse:
    """WebSocket接続用トークンを発行します。

    指定されたセッションIDに紐付く一回限りのWebSocketトークンを発行します。
    トークンは短命（設定値、既定60秒）で、使用時に消費されます。

    Args:
        request: Starlette リクエストオブジェクト

    Returns:
        トークン情報を含む JSONResponse: {ws_token: str, expires_in_seconds: int}

    Raises:
        HTTPException: 認証失敗(401)、セッションID形式不正(400)、セッション不在(404)
    """
    await verify_gateway_token(request)

    session_id = request.path_params.get("session_id")
    if not session_id or not _validate_session_id(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    # セッションの存在確認
    if not await anyio.to_thread.run_sync(session_exists, session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # トークン発行
    config = get_config()
    ttl_seconds = config.terminal_ws_token_ttl_seconds
    ws_token = await terminal_ws_token_store.issue(session_id, ttl_seconds)

    return JSONResponse(
        {
            "ws_token": ws_token,
            "expires_in_seconds": ttl_seconds,
        },
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


async def get_session_snapshot(request: Request) -> JSONResponse:
    """指定された tmux セッションのプレーンテキスト snapshot を返す。"""
    await verify_gateway_token(request)

    session_id = request.path_params.get("session_id")
    if not session_id or not _validate_session_id(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    if not await anyio.to_thread.run_sync(session_exists, session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    manager = TmuxAttachManager(session_id)
    try:
        snapshot = await manager.capture_snapshot(include_escape_sequences=False)
    except Exception as e:
        logger.error("Failed to capture snapshot for %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail="Failed to capture snapshot") from e

    response = TerminalSnapshotResponse(
        session_id=session_id,
        content=snapshot.decode("utf-8", errors="replace"),
    )
    return JSONResponse(
        response.model_dump(),
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


def get_terminal_routes() -> list[Route]:
    """Terminal API ルートを取得します。

    Returns:
        ルート定義のリスト
    """
    return [
        Route("/v1/terminal/sessions", get_sessions, methods=["GET"]),
        Route("/v1/terminal/sessions/{session_id}", get_session, methods=["GET"]),
        Route(
            "/v1/terminal/sessions/{session_id}/ws-token",
            issue_ws_token,
            methods=["POST"],
        ),
        Route(
            "/v1/terminal/sessions/{session_id}/snapshot",
            get_session_snapshot,
            methods=["GET"],
        ),
        WebSocketRoute("/ws/terminal", terminal_websocket),
    ]


async def terminal_websocket(websocket: WebSocket) -> None:
    """端末WebSocketエンドポイント。

    tmuxセッションとの双方向通信を提供する。

    Args:
        websocket: WebSocket接続

    Query Parameters:
        session_id: tmuxセッションID (例: agent-0001)

    メッセージ形式 (Client -> Server):
        - {"type": "auth", "ws_token": "..."}
        - {"type": "input", "data_b64": "..."}
        - {"type": "resize", "cols": 120, "rows": 30}
        - {"type": "ping"}

    メッセージ形式 (Server -> Client):
        - {"type": "output", "data_b64": "..."}
        - {"type": "status", "state": "connected|reconnecting|closed"}
        - {"type": "error", "code": "...", "message": "..."}
        - {"type": "ping"}
    """
    # クエリパラメータを取得
    session_id = websocket.query_params.get("session_id")

    if not _validate_websocket_client_ip(websocket):
        await websocket.close(code=1008, reason="Invalid client ip")
        return

    if not _validate_websocket_host_header(websocket):
        await websocket.close(code=1008, reason="Invalid host")
        return

    if not _validate_websocket_origin_header(websocket):
        await websocket.close(code=1008, reason="Invalid origin")
        return

    # パラメータ検証
    if not session_id:
        logger.warning("Missing required parameter: session_id")
        await websocket.close(
            code=1008, reason="Missing required parameter: session_id"
        )
        return

    # セッションIDのバリデーション (形式: agent-XXXX)
    if not _validate_session_id(session_id):
        logger.warning("Invalid session_id format: %s", session_id)
        await websocket.close(code=1008, reason="Invalid session_id format")
        return

    # WebSocket接続を確立してから認証メッセージを受け取る
    await websocket.accept()

    if not await _authenticate_websocket(websocket, session_id):
        return

    # セッションが実際に存在するか確認
    if not await anyio.to_thread.run_sync(session_exists, session_id):
        logger.warning("Session does not exist: %s", session_id)
        await websocket.close(code=1008, reason="Session does not exist")
        return

    logger.info("WebSocket connection established for session: %s", session_id)

    # ハンドラーを作成して実行
    handler = TerminalWebSocketHandler(websocket, session_id)

    try:
        await handler.handle()
    except Exception as e:
        logger.error("Error in terminal websocket for session %s: %s", session_id, e)
    finally:
        logger.info("WebSocket connection closed for session: %s", session_id)


def _validate_session_id(session_id: str) -> bool:
    """セッションIDの形式を検証する。

    Args:
        session_id: 検証するセッションID

    Returns:
        形式が正しい場合はTrue、そうでない場合はFalse
    """
    # 形式: agent-XXXX (XXXXは4桁の数字)
    pattern = r"^agent-[0-9]{4}$"
    return bool(re.match(pattern, session_id))


def _extract_host_without_port(host_header: str) -> str:
    """Host ヘッダーからホスト名部分のみを抽出する。"""
    host = host_header.strip().lower()
    if host.startswith("["):
        closing = host.find("]")
        if closing != -1:
            return host[1:closing]
        return host.strip("[]")
    return host.split(":", maxsplit=1)[0]


def _is_allowed_request_host(host: str) -> bool:
    """HTTP/WS リクエストの Host が許可対象か判定する。"""
    normalized = host.strip().lower().rstrip(".")
    return normalized in LOCAL_ALLOWED_HOSTS or is_tailscale_hostname(normalized)


def _validate_websocket_host_header(websocket: WebSocket) -> bool:
    """WebSocket の Host ヘッダーを検証する。"""
    host_header = websocket.headers.get("host")
    if not host_header:
        logger.warning("WebSocket rejected: missing Host header")
        return False
    host = _extract_host_without_port(host_header)
    if not _is_allowed_request_host(host):
        logger.warning("WebSocket rejected: invalid Host header (%s)", host)
        return False
    return True


def _validate_websocket_client_ip(websocket: WebSocket) -> bool:
    """WebSocket の接続元IPを検証する。"""
    client = websocket.client
    if client is None:
        client_host = ""
    elif hasattr(client, "host"):
        client_host = str(client.host)
    elif isinstance(client, (tuple, list)) and client:
        client_host = str(client[0])
    else:
        client_host = str(client)
    if not is_allowed_client_ip(client_host):
        logger.warning("WebSocket rejected: invalid client ip (%s)", client_host)
        return False
    return True


def _validate_websocket_origin_header(websocket: WebSocket) -> bool:
    """WebSocket の Origin ヘッダーを検証する。"""
    origin = websocket.headers.get("origin")
    if origin is None:
        # 非ブラウザクライアントとの互換のため未設定は許可する
        return True

    normalized_origin = origin.strip().lower()
    if normalized_origin in WEBVIEW_ALLOWED_ORIGINS:
        # Android WebView (file://) 互換
        return True

    parsed = urlparse(normalized_origin)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        logger.warning("WebSocket rejected: invalid Origin format (%s)", origin)
        return False

    if not is_tailscale_hostname(host):
        logger.warning("WebSocket rejected: non-tailscale Origin (%s)", origin)
        return False

    host_header = websocket.headers.get("host")
    if not host_header:
        logger.warning("WebSocket rejected: missing Host header")
        return False

    request_host = _extract_host_without_port(host_header).rstrip(".")
    if host != request_host:
        logger.warning(
            "WebSocket rejected: Origin host does not match Host (%s vs %s)",
            host,
            request_host,
        )
        return False

    return True


def _extract_preview_lines(snapshot_text: str) -> tuple[bool, list[str]]:
    """スナップショットテキストからプレビュー行を抽出します。

    ANSI エスケープシーケンスと制御文字を除去し、
    空でない行を返します。

    Args:
        snapshot_text: スナップショットテキスト
    Returns:
        (preview_available, preview_lines) タプル
        - preview_available: プレビューが利用可能かどうか
        - preview_lines: プレビュー行のリスト
    """
    # ANSI エスケープシーケンスを除去
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    clean_text = ansi_escape.sub("", snapshot_text)

    # 制御文字を除去（改行とタブは保持）
    control_chars = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
    clean_text = control_chars.sub("", clean_text)

    # 行に分割し、空行を除去
    lines = [line.rstrip() for line in clean_text.split("\n")]
    non_empty_lines = [line for line in lines if line]

    if not non_empty_lines:
        return (False, [])

    return (True, non_empty_lines)


async def _build_session_response(session_id: str, session) -> dict:
    """tmux セッション情報を API レスポンス形式に変換します。

    非同期関数として定義し、プレビュースナップショットの取得をサポートします。
    """
    response = {
        "session_id": session_id,
        "name": session.name,
        "last_activity": session.last_activity.isoformat(),
        "created_at": session.created_at.isoformat(),
        "status": SessionStatus.CONNECTED.value,
        "preview_available": False,
        "preview_lines": [],
        "title": None,
        "current_path": None,
    }

    response["title"], response["current_path"] = await anyio.to_thread.run_sync(
        get_active_pane_metadata,
        session_id,
    )

    # プレビュースナップショットの取得を試みる
    try:
        manager = TmuxAttachManager(session_id)
        snapshot = await manager.capture_snapshot(include_escape_sequences=False)
        snapshot_text = snapshot.decode("utf-8", errors="replace")
        preview_available, preview_lines = _extract_preview_lines(snapshot_text)
        response["preview_available"] = preview_available
        response["preview_lines"] = preview_lines
    except Exception as e:
        logger.debug("Failed to capture preview for %s: %s", session_id, e)
        # 失敗時はデフォルト値（プレビューなし）を使用

    return response


async def _authenticate_websocket(websocket: WebSocket, session_id: str) -> bool:
    """WebSocket接続の初回認証を行う。

    ws_token を使用して一回限りの認証を行います。
    """
    try:
        auth_message = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=AUTH_TIMEOUT_SECONDS,
        )
        payload = json.loads(auth_message)
    except asyncio.TimeoutError:
        logger.warning("Authentication timeout for session: %s", session_id)
        await websocket.close(code=1008, reason="Unauthorized")
        return False
    except (json.JSONDecodeError, WebSocketDisconnect):
        logger.warning("Authentication message is invalid for session: %s", session_id)
        await websocket.close(code=1008, reason="Unauthorized")
        return False
    except Exception:
        logger.exception("Unexpected authentication error for session: %s", session_id)
        await websocket.close(code=1011, reason="Internal error")
        return False

    if not isinstance(payload, dict):
        logger.warning(
            "Authentication payload is not an object for session: %s", session_id
        )
        await websocket.close(code=1008, reason="Unauthorized")
        return False

    if payload.get("type") != "auth":
        logger.warning(
            "Authentication message type mismatch for session: %s", session_id
        )
        await websocket.close(code=1008, reason="Unauthorized")
        return False

    ws_token = payload.get("ws_token")
    if not isinstance(ws_token, str) or not ws_token:
        logger.warning("Missing ws_token in auth message for session: %s", session_id)
        await websocket.close(code=1008, reason="Unauthorized")
        return False

    success, token_session_id = await terminal_ws_token_store.consume(ws_token)
    if not success or token_session_id != session_id:
        logger.warning("Authentication failed for session: %s", session_id)
        await websocket.close(code=1008, reason="Unauthorized")
        return False

    return True
