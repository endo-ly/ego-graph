"""Terminal API の統合テスト。

WebSocket接続とメッセージ handling をテストする。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.api.terminal import terminal_websocket
from gateway.domain.models import (
    WSErrorMessage,
    WSInputMessage,
    WSOutputMessage,
    WSPingMessage,
    WSPongMessage,
    WSResizeMessage,
    WSStatusMessage,
)

MOCK_TAILSCALE_HOST = "mock-gateway.test.ts.net"
MOCK_TAILSCALE_ORIGIN = f"https://{MOCK_TAILSCALE_HOST}"
MOCK_OTHER_TAILSCALE_ORIGIN = "https://other-gateway.test.ts.net"

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def valid_token():
    """有効な認証トークン。"""
    return "valid_token_12345678901234567890"


@pytest.fixture
def invalid_token():
    """無効な認証トークン。"""
    return "invalid_token"


@pytest.fixture
def valid_session_id():
    """有効なセッションID。"""
    return "agent-0001"


@pytest.fixture
def invalid_session_id():
    """無効なセッションID。"""
    return "invalid-session"


@pytest.fixture
def valid_ws_headers():
    """有効な WebSocket ヘッダー。"""
    return {
        "host": MOCK_TAILSCALE_HOST,
        "origin": MOCK_TAILSCALE_ORIGIN,
    }


# ============================================================================
# WebSocket認証テスト
# ============================================================================


class TestWebSocketAuthentication:
    """WebSocket認証のテスト。"""

    @pytest.mark.asyncio
    async def test_websocket_accepts_valid_token(
        self,
        valid_token,
        valid_session_id,
        valid_ws_headers,
    ):
        """有効なトークンでWebSocket接続が確立されることを確認する。"""
        # Arrange
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = valid_ws_headers
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.accept = AsyncMock()
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        mock_websocket.close = AsyncMock()

        with (
            patch(
                "gateway.api.terminal.terminal_ws_token_store",
            ) as mock_store,
            patch(
                "gateway.api.terminal.anyio.to_thread.run_sync",
                return_value=True,
            ),
            patch(
                "gateway.api.terminal.TerminalWebSocketHandler"
            ) as mock_handler_class,
        ):
            mock_store.consume = AsyncMock(return_value=(True, valid_session_id))
            mock_handler = MagicMock()
            mock_handler.handle = AsyncMock()
            mock_handler_class.return_value = mock_handler

            # Act
            await terminal_websocket(mock_websocket)

            # Assert
            mock_websocket.accept.assert_called_once()
            mock_store.consume.assert_called_once_with(valid_token)
            mock_handler.handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_rejects_invalid_token(
        self,
        invalid_token,
        valid_session_id,
        valid_ws_headers,
    ):
        """無効なトークンでWebSocket接続が拒否されることを確認する。"""
        # Arrange
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = valid_ws_headers
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{invalid_token}"}}'
        )
        mock_websocket.accept = AsyncMock()
        mock_websocket.close = AsyncMock()

        with patch("gateway.api.terminal.terminal_ws_token_store") as mock_store:
            mock_store.consume = AsyncMock(return_value=(False, None))

            # Act
            await terminal_websocket(mock_websocket)

            # Assert
            mock_websocket.accept.assert_called_once()
            mock_websocket.close.assert_called_once_with(
                code=1008, reason="Unauthorized"
            )

    @pytest.mark.asyncio
    async def test_websocket_rejects_missing_token(
        self,
        valid_session_id,
        valid_ws_headers,
    ):
        """トークンが欠落している場合、WebSocket接続が拒否されることを確認する。"""
        # Arrange
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = valid_ws_headers
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.receive_text = AsyncMock(return_value='{"type":"auth"}')
        mock_websocket.accept = AsyncMock()
        mock_websocket.close = AsyncMock()

        # Act
        await terminal_websocket(mock_websocket)

        # Assert
        mock_websocket.accept.assert_called_once()
        mock_websocket.close.assert_called_once_with(code=1008, reason="Unauthorized")

    @pytest.mark.asyncio
    async def test_websocket_rejects_token_replay(
        self,
        valid_token,
        valid_session_id,
        valid_ws_headers,
    ):
        """トークンの再利用（リプレイ）が拒否されることを確認する。"""
        first_websocket = MagicMock()
        first_websocket.query_params = {"session_id": valid_session_id}
        first_websocket.headers = valid_ws_headers
        first_websocket.client = ("100.100.100.100", 12345)
        first_websocket.accept = AsyncMock()
        first_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        first_websocket.close = AsyncMock()

        replay_websocket = MagicMock()
        replay_websocket.query_params = {"session_id": valid_session_id}
        replay_websocket.headers = valid_ws_headers
        replay_websocket.client = ("100.100.100.100", 12345)
        replay_websocket.accept = AsyncMock()
        replay_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        replay_websocket.close = AsyncMock()

        with (
            patch(
                "gateway.api.terminal.terminal_ws_token_store",
            ) as mock_store,
            patch(
                "gateway.api.terminal.anyio.to_thread.run_sync",
                return_value=True,
            ),
            patch(
                "gateway.api.terminal.TerminalWebSocketHandler"
            ) as mock_handler_class,
        ):
            mock_store.consume = AsyncMock(
                side_effect=[
                    (True, valid_session_id),
                    (False, None),
                ]
            )
            mock_handler = MagicMock()
            mock_handler.handle = AsyncMock()
            mock_handler_class.return_value = mock_handler

            await terminal_websocket(first_websocket)
            await terminal_websocket(replay_websocket)

            first_websocket.accept.assert_called_once()
            replay_websocket.accept.assert_called_once()
            replay_websocket.close.assert_called_once_with(
                code=1008,
                reason="Unauthorized",
            )

    @pytest.mark.asyncio
    async def test_websocket_rejects_expired_token(
        self,
        valid_token,
        valid_session_id,
        valid_ws_headers,
    ):
        """期限切れトークンが拒否されることを確認する。"""
        # Arrange
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = valid_ws_headers
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.accept = AsyncMock()
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        mock_websocket.close = AsyncMock()

        with patch("gateway.api.terminal.terminal_ws_token_store") as mock_store:
            # Expired token returns False
            mock_store.consume = AsyncMock(return_value=(False, None))

            # Act
            await terminal_websocket(mock_websocket)

            # Assert
            mock_websocket.accept.assert_called_once()
            mock_websocket.close.assert_called_once_with(
                code=1008, reason="Unauthorized"
            )

    @pytest.mark.asyncio
    async def test_websocket_rejects_token_session_mismatch(
        self,
        valid_token,
        valid_session_id,
        valid_ws_headers,
    ):
        """トークンのセッションIDが一致しない場合、拒否されることを確認する。"""
        # Arrange
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = valid_ws_headers
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.accept = AsyncMock()
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        mock_websocket.close = AsyncMock()

        with patch("gateway.api.terminal.terminal_ws_token_store") as mock_store:
            # Token is valid but for different session
            mock_store.consume = AsyncMock(return_value=(True, "agent-9999"))

            # Act
            await terminal_websocket(mock_websocket)

            # Assert
            mock_websocket.accept.assert_called_once()
            mock_websocket.close.assert_called_once_with(
                code=1008, reason="Unauthorized"
            )


# ============================================================================
# セッションIDバリデーションテスト
# ============================================================================


class TestSessionIdValidation:
    """セッションIDバリデーションのテスト。"""

    @pytest.mark.asyncio
    async def test_websocket_rejects_invalid_session_id(
        self,
        invalid_session_id,
        valid_ws_headers,
    ):
        """無効なセッションIDでWebSocket接続が拒否されることを確認する。"""
        # Arrange
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": invalid_session_id}
        mock_websocket.headers = valid_ws_headers
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.close = AsyncMock()

        # Act (no patch needed - validation happens before auth)
        await terminal_websocket(mock_websocket)

        # Assert
        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once_with(
            code=1008, reason="Invalid session_id format"
        )

    @pytest.mark.asyncio
    async def test_websocket_rejects_suffixed_session_id(self, valid_ws_headers):
        """接尾辞付きのセッションIDでWebSocket接続が拒否されることを確認する。"""
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": "agent-0001-8"}
        mock_websocket.headers = valid_ws_headers
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.close = AsyncMock()

        await terminal_websocket(mock_websocket)

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once_with(
            code=1008, reason="Invalid session_id format"
        )

    @pytest.mark.asyncio
    async def test_websocket_rejects_invalid_host(self, valid_session_id, valid_token):
        """不正なHostヘッダーでWebSocket接続が拒否されることを確認する。"""
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = {
            "host": "example.com",
            "origin": MOCK_TAILSCALE_ORIGIN,
        }
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.accept = AsyncMock()
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        mock_websocket.close = AsyncMock()

        await terminal_websocket(mock_websocket)

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once_with(code=1008, reason="Invalid host")

    @pytest.mark.asyncio
    async def test_websocket_rejects_invalid_origin(
        self,
        valid_session_id,
        valid_token,
    ):
        """不正なOriginヘッダーでWebSocket接続が拒否されることを確認する。"""
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = {
            "host": MOCK_TAILSCALE_HOST,
            "origin": "https://example.com",
        }
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.accept = AsyncMock()
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        mock_websocket.close = AsyncMock()

        await terminal_websocket(mock_websocket)

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once_with(
            code=1008,
            reason="Invalid origin",
        )

    @pytest.mark.asyncio
    async def test_websocket_rejects_origin_host_mismatch(
        self,
        valid_session_id,
        valid_token,
    ):
        """Origin の host と Host ヘッダーが不一致な場合に拒否されることを確認する。"""
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = {
            "host": MOCK_TAILSCALE_HOST,
            "origin": MOCK_OTHER_TAILSCALE_ORIGIN,
        }
        mock_websocket.client = ("100.100.100.100", 12345)
        mock_websocket.accept = AsyncMock()
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        mock_websocket.close = AsyncMock()

        await terminal_websocket(mock_websocket)

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once_with(
            code=1008,
            reason="Invalid origin",
        )

    @pytest.mark.asyncio
    async def test_websocket_rejects_non_tailnet_client_ip(
        self,
        valid_session_id,
        valid_token,
    ):
        """Tailnet外IPの接続元はWebSocket握手時に拒否することを確認する。"""
        mock_websocket = MagicMock()
        mock_websocket.query_params = {"session_id": valid_session_id}
        mock_websocket.headers = {
            "host": MOCK_TAILSCALE_HOST,
            "origin": MOCK_TAILSCALE_ORIGIN,
        }
        mock_websocket.client = ("8.8.8.8", 44321)
        mock_websocket.accept = AsyncMock()
        mock_websocket.receive_text = AsyncMock(
            return_value=f'{{"type":"auth","ws_token":"{valid_token}"}}'
        )
        mock_websocket.close = AsyncMock()

        await terminal_websocket(mock_websocket)

        mock_websocket.accept.assert_not_called()
        mock_websocket.close.assert_called_once_with(
            code=1008,
            reason="Invalid client ip",
        )


# ============================================================================
# WebSocketメッセージ handling テスト
# ============================================================================


class TestWebSocketMessageHandling:
    """WebSocketメッセージ handling のテスト。"""

    def test_input_message_handling(self):
        """入力メッセージが正しく処理されることを確認する。"""
        # Arrange
        message = WSInputMessage(data_b64="SGVsbG8=")  # "Hello" in base64

        # Act
        data = message.decode_data()

        # Assert
        assert data == b"Hello"

    def test_output_message_creation(self):
        """出力メッセージが正しく作成されることを確認する。"""
        # Arrange
        test_data = b"World"

        # Act
        message = WSOutputMessage.from_bytes(test_data)

        # Assert
        assert message.type == "output"
        assert message.data_b64 == "V29ybGQ="  # "World" in base64

    def test_invalid_base64_rejected(self):
        """無効なBase64エンコーディングが拒否されることを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValueError, match="Invalid base64"):
            WSInputMessage(data_b64="invalid_base64!@")


# ============================================================================
# WebSocketメッセージスキーマテスト
# ============================================================================


class TestWebSocketMessageSchemas:
    """WebSocketメッセージスキーマのテスト。"""

    def test_input_message_schema(self):
        """入力メッセージスキーマを検証する。"""
        # Arrange
        data = {"type": "input", "data_b64": "SGVsbG8="}

        # Act
        message = WSInputMessage(**data)

        # Assert
        assert message.type == "input"
        assert message.data_b64 == "SGVsbG8="

    def test_resize_message_schema(self):
        """画面サイズ変更メッセージスキーマを検証する。"""
        # Arrange
        data = {"type": "resize", "cols": 120, "rows": 30}

        # Act
        message = WSResizeMessage(**data)

        # Assert
        assert message.type == "resize"
        assert message.cols == 120
        assert message.rows == 30

    def test_ping_message_schema(self):
        """Pingメッセージスキーマを検証する。"""
        # Arrange
        data = {"type": "ping"}

        # Act
        message = WSPingMessage(**data)

        # Assert
        assert message.type == "ping"

    def test_status_message_schema(self):
        """状態メッセージスキーマを検証する。"""
        # Arrange
        data = {"type": "status", "state": "connected"}

        # Act
        message = WSStatusMessage(**data)

        # Assert
        assert message.type == "status"
        assert message.state == "connected"

    def test_error_message_schema(self):
        """エラーメッセージスキーマを検証する。"""
        # Arrange
        data = {"type": "error", "code": "test_error", "message": "Test error message"}

        # Act
        message = WSErrorMessage(**data)

        # Assert
        assert message.type == "error"
        assert message.code == "test_error"
        assert message.message == "Test error message"

    def test_pong_message_schema(self):
        """Pongメッセージスキーマを検証する。"""
        # Arrange
        data = {"type": "pong"}

        # Act
        message = WSPongMessage(**data)

        # Assert
        assert message.type == "pong"
