"""WebSocketハンドラーの単体テスト。"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.domain.models import WSInputMessage
from gateway.services.websocket_handler import TerminalWebSocketHandler

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def session_id():
    """テスト用セッションID。"""
    return "agent-0001"


@pytest.fixture
def mock_websocket():
    """モックWebSocket接続。"""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def websocket_handler(mock_websocket, session_id):
    """テスト用WebSocketハンドラー。"""
    return TerminalWebSocketHandler(mock_websocket, session_id)


# ============================================================================
# 初期化テスト
# ============================================================================


class TestTerminalWebSocketHandlerInit:
    """TerminalWebSocketHandler初期化のテスト。"""

    def test_init_with_websocket_and_session_id(
        self, websocket_handler, session_id, mock_websocket
    ):
        """WebSocketとセッションIDで初期化されることを確認する。"""
        # Assert
        assert websocket_handler._session_id == session_id
        assert not websocket_handler._running
        assert websocket_handler._tasks == []


# ============================================================================
# クライアントメッセージ処理テスト
# ============================================================================


class TestHandleClientMessage:
    """クライアントメッセージ処理のテスト。"""

    @pytest.mark.asyncio
    async def test_handle_input_message(self, websocket_handler):
        """入力メッセージが正しく処理されることを確認する。"""
        # Arrange
        message_data = {"type": "input", "data_b64": "SGVsbG8="}  # "Hello"
        pty_manager = MagicMock()
        pty_manager.write_input = AsyncMock()
        websocket_handler._pty_manager = pty_manager

        # Act
        await websocket_handler._handle_client_message(json.dumps(message_data))

        # Assert
        pty_manager.write_input.assert_called_once_with(b"Hello")

    @pytest.mark.asyncio
    async def test_handle_resize_message(self, websocket_handler):
        """画面サイズ変更メッセージが正しく処理されることを確認する。"""
        # Arrange
        message_data = {"type": "resize", "cols": 120, "rows": 30}
        pty_manager = MagicMock()
        pty_manager.resize_window = AsyncMock()
        websocket_handler._pty_manager = pty_manager

        # Act
        await websocket_handler._handle_client_message(json.dumps(message_data))

        # Assert
        pty_manager.resize_window.assert_called_once_with(cols=120, rows=30)

    @pytest.mark.asyncio
    async def test_handle_scroll_message(self, websocket_handler):
        """スクロールメッセージが正しく処理されることを確認する。"""
        message_data = {"type": "scroll", "lines": -4}
        pty_manager = MagicMock()
        pty_manager.route_scroll = AsyncMock()
        websocket_handler._pty_manager = pty_manager

        await websocket_handler._handle_client_message(json.dumps(message_data))

        pty_manager.route_scroll.assert_awaited_once_with(-4)

    @pytest.mark.asyncio
    async def test_handle_scroll_message_keeps_raw_line_delta(self, websocket_handler):
        """クライアントの行数がそのままスクロール処理へ渡ることを確認する。"""
        message_data = {"type": "scroll", "lines": -1}
        pty_manager = MagicMock()
        pty_manager.route_scroll = AsyncMock()
        websocket_handler._pty_manager = pty_manager

        await websocket_handler._handle_client_message(json.dumps(message_data))
        pty_manager.route_scroll.assert_awaited_once_with(-1)

    @pytest.mark.asyncio
    async def test_handle_ping_message(self, websocket_handler):
        """Pingメッセージが正しく処理されることを確認する。"""
        # Arrange
        message_data = {"type": "ping"}

        # Act
        await websocket_handler._handle_client_message(json.dumps(message_data))

        # Assert
        websocket_handler._websocket.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_handle_invalid_message_format(self, websocket_handler):
        """無効なメッセージ形式でエラーメッセージが送信されることを確認する。"""
        # Arrange
        invalid_message = "invalid json"

        # Act
        await websocket_handler._handle_client_message(invalid_message)

        # Assert
        # エラーメッセージが送信されることを確認
        websocket_handler._websocket.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_handle_unknown_message_type(self, websocket_handler):
        """未知のメッセージタイプでエラーが発生しないことを確認する。"""
        # Arrange
        message_data = {"type": "unknown"}

        # Act
        await websocket_handler._handle_client_message(json.dumps(message_data))

        # Assert - エラーが発生しないことを確認


# ============================================================================
# 送信メソッドテスト
# ============================================================================


class TestSendMethods:
    """送信メソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_send_status(self, websocket_handler):
        """状態メッセージが正しく送信されることを確認する。"""
        # Arrange
        test_state = "connected"

        # Act
        await websocket_handler._send_status(test_state)

        # Assert
        websocket_handler._websocket.send_json.assert_called_once()
        call_args = websocket_handler._websocket.send_json.call_args[0][0]
        assert call_args["type"] == "status"
        assert call_args["state"] == test_state

    @pytest.mark.asyncio
    async def test_send_error(self, websocket_handler):
        """エラーメッセージが正しく送信されることを確認する。"""
        # Arrange
        test_code = "test_error"
        test_message = "Test error message"

        # Act
        await websocket_handler._send_error(test_code, test_message)

        # Assert
        websocket_handler._websocket.send_json.assert_called_once()
        call_args = websocket_handler._websocket.send_json.call_args[0][0]
        assert call_args["type"] == "error"
        assert call_args["code"] == test_code
        assert call_args["message"] == test_message

    @pytest.mark.asyncio
    async def test_send_pong(self, websocket_handler):
        """Pongメッセージが正しく送信されることを確認する。"""
        # Act
        await websocket_handler._send_pong()

        # Assert
        websocket_handler._websocket.send_json.assert_called_once()
        call_args = websocket_handler._websocket.send_json.call_args[0][0]
        assert call_args["type"] == "pong"


# ============================================================================
# メッセージデコードテスト
# ============================================================================


class TestWSInputMessage:
    """WSInputMessageのテスト。"""

    def test_decode_data(self):
        """Base64エンコードされたデータが正しくデコードされることを確認する。"""
        # Arrange
        test_string = "Hello, World!"

        encoded = base64.b64encode(test_string.encode()).decode()
        message = WSInputMessage(data_b64=encoded)

        # Act
        decoded = message.decode_data()

        # Assert
        assert decoded == test_string.encode()

    def test_decode_data_with_unicode(self):
        """Unicode文字を含むデータが正しくデコードされることを確認する。"""
        # Arrange
        test_string = "こんにちは世界"

        encoded = base64.b64encode(test_string.encode()).decode()
        message = WSInputMessage(data_b64=encoded)

        # Act
        decoded = message.decode_data()

        # Assert
        assert decoded == test_string.encode()

    def test_validate_base64_with_invalid_data(self):
        """無効なBase64データでバリデーションエラーが発生することを確認する。"""
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid base64"):
            WSInputMessage(data_b64="invalid_base64!@#")

    def test_validate_base64_with_valid_data(self):
        """有効なBase64データでバリデーションが成功することを確認する。"""
        # Arrange

        test_string = "Valid data"
        encoded = base64.b64encode(test_string.encode()).decode()

        # Act - エラーが発生しないことを確認
        message = WSInputMessage(data_b64=encoded)

        # Assert
        assert message.data_b64 == encoded
