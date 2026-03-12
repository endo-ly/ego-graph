"""WebSocket端末接続のハンドラー。

クライアントとの双方向通信とPTYプロセスの管理を担当する。
"""

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError
from starlette.websockets import WebSocket

from gateway.domain.models import (
    WSErrorMessage,
    WSInputMessage,
    WSOutputMessage,
    WSPingMessage,
    WSPongMessage,
    WSResizeMessage,
    WSScrollMessage,
    WSStatusMessage,
)
from gateway.services.pty_manager import TmuxAttachManager

logger = logging.getLogger(__name__)

# WebSocket設定
WS_PING_INTERVAL: int = 30  # 秒
WS_PING_TIMEOUT: int = 20  # 秒
BUFFER_SIZE: int = 8192  # バイト


class TerminalWebSocketHandler:
    """端末WebSocket接続のハンドラー。

    クライアントから受信したメッセージをPTYに転送し、
    PTYからの出力をクライアントに送信する。
    """

    def __init__(self, websocket: WebSocket, session_id: str) -> None:
        """TerminalWebSocketHandlerを初期化する。

        Args:
            websocket: WebSocket接続オブジェクト
            session_id: tmuxセッションID
        """
        self._websocket = websocket
        self._session_id = session_id
        self._pty_manager = TmuxAttachManager(session_id)
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    async def handle(self) -> None:
        """WebSocket接続を処理する。

        接続の確立、メッセージの送受信、切断処理を行う。
        """
        self._running = True
        try:
            # PTYにattach
            await self._pty_manager.attach_session()
            await self._send_status("connected")

            # 並行処理タスクを作成
            self._tasks = [
                asyncio.create_task(self._receive_from_client()),
                asyncio.create_task(self._send_to_client()),
                asyncio.create_task(self._ping_loop()),
            ]

            # 全てのタスクが完了するのを待機
            await asyncio.gather(*self._tasks)

        except Exception as e:
            logger.error("Error in WebSocket handler: %s", e)
            await self._send_error("internal_error", str(e))
        finally:
            await self._cleanup()

    async def _receive_from_client(self) -> None:
        """クライアントからのメッセージを受信してPTYに転送する。"""
        while self._running:
            try:
                message = await self._websocket.receive_text()
                await self._handle_client_message(message)
            except Exception as e:
                if self._running:
                    logger.error("Error receiving from client: %s", e)
                    self._running = False
                break

    async def _handle_client_message(self, message: str) -> None:
        """クライアントからのメッセージを処理する。

        Args:
            message: JSON形式のメッセージ文字列
        """
        try:
            data: dict[str, Any] = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "input":
                await self._handle_input(WSInputMessage(**data))
            elif msg_type == "resize":
                await self._handle_resize(WSResizeMessage(**data))
            elif msg_type == "scroll":
                await self._handle_scroll(WSScrollMessage(**data))
            elif msg_type == "ping":
                await self._handle_ping(WSPingMessage(**data))
            else:
                logger.warning("Unknown message type: %s", msg_type)

        except ValidationError as e:
            logger.error("Invalid message format: %s", e)
            await self._send_error("invalid_message", str(e))
        except Exception as e:
            logger.error("Error handling client message: %s", e)
            await self._send_error("message_error", str(e))

    async def _handle_input(self, message: WSInputMessage) -> None:
        """入力メッセージを処理する。

        Args:
            message: 入力メッセージ
        """
        try:
            data = message.decode_data()
            await self._pty_manager.write_input(data)
        except Exception as e:
            logger.error("Failed to write input: %s", e)
            await self._send_error("input_error", str(e))

    async def _handle_resize(self, message: WSResizeMessage) -> None:
        """画面サイズ変更メッセージを処理する。

        tmuxのresize-windowコマンドを実行する。

        Args:
            message: 画面サイズ変更メッセージ
        """
        try:
            await self._pty_manager.resize_window(
                cols=message.cols,
                rows=message.rows,
            )
            logger.info(
                "Resized session %s to %sx%s",
                self._session_id,
                message.cols,
                message.rows,
            )
        except Exception as e:
            logger.error("Failed to resize session %s: %s", self._session_id, e)
            await self._send_error("resize_error", str(e))

    async def _handle_ping(self, message: WSPingMessage) -> None:
        """Pingメッセージを処理する。

        Args:
            message: Pingメッセージ
        """
        await self._send_pong()

    async def _handle_scroll(self, message: WSScrollMessage) -> None:
        """スクロールメッセージを処理する。"""
        try:
            await self._pty_manager.route_scroll(message.lines)
        except Exception as e:
            logger.error("Failed to scroll session %s: %s", self._session_id, e)
            await self._send_error("scroll_error", str(e))

    async def _send_to_client(self) -> None:
        """PTYからの出力をクライアントに送信する。"""
        while self._running:
            try:
                # PTYから出力を読み込み
                data = await self._pty_manager.read_output(BUFFER_SIZE)
                if data:
                    # Base64エンコードして送信
                    message = WSOutputMessage.from_bytes(data, is_snapshot=False)
                    await self._send_json(message.model_dump())
                else:
                    await asyncio.sleep(0.05)
            except Exception as e:
                if self._running:
                    logger.error("Error sending to client: %s", e)
                    self._running = False
                break

    async def _ping_loop(self) -> None:
        """定期的にPingを送信するハートビートループ。"""
        while self._running:
            try:
                await asyncio.sleep(WS_PING_INTERVAL)
                if self._running:
                    await self._send_pong()
            except Exception as e:
                if self._running:
                    logger.debug("Ping loop stopped: %s", e)
                break

    async def _send_json(self, data: dict[str, Any]) -> None:
        """JSONメッセージを送信する。

        Args:
            data: 送信するデータ
        """
        try:
            await self._websocket.send_json(data)
        except Exception:
            self._running = False
            raise

    async def _send_status(self, state: str) -> None:
        """状態メッセージを送信する。

        Args:
            state: 接続状態 (connected/reconnecting/closed)
        """
        message = WSStatusMessage(state=state)
        await self._send_json(message.model_dump())

    async def _send_error(self, code: str, message_text: str) -> None:
        """エラーメッセージを送信する。

        Args:
            code: エラーコード
            message_text: エラーメッセージ
        """
        message = WSErrorMessage(code=code, message=message_text)
        await self._send_json(message.model_dump())

    async def _send_pong(self) -> None:
        """Pongメッセージを送信する。"""
        message = WSPongMessage()
        await self._send_json(message.model_dump())

    async def _cleanup(self) -> None:
        """リソースを解放する。"""
        self._running = False

        # タスクをキャンセル
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # PTYをdetach
        await self._pty_manager.detach_session()

        # 接続状態を通知
        try:
            await self._send_status("closed")
        except Exception:
            pass  # 接続が既に閉じている場合は無視

        logger.info("WebSocket handler cleaned up for session: %s", self._session_id)
