"""WebSocketトークン発行APIの単体テスト。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.exceptions import HTTPException

from gateway.api.terminal import issue_ws_token

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_request():
    """テスト用リクエスト。"""
    request = MagicMock()
    request.headers = {}
    request.path_params = {}
    return request


# ============================================================================
# issue_ws_tokenテスト
# ============================================================================


class TestIssueWsToken:
    """issue_ws_tokenエンドポイントのテスト。"""

    @pytest.mark.asyncio
    async def test_issue_ws_token_does_not_require_api_key(self, mock_request):
        """APIキー未指定でも、session_id不正時は400になることを確認する。"""
        with pytest.raises(HTTPException) as exc_info:
            await issue_ws_token(mock_request)

        assert exc_info.value.status_code == 400
        assert "Invalid session_id format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_issue_ws_token_missing_session_id_returns_400(self, mock_request):
        """session_idが欠落している場合に400エラーを返すことを確認する。"""
        # Arrange
        mock_request.path_params = {}  # session_idを含まない

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await issue_ws_token(mock_request)

        assert exc_info.value.status_code == 400
        assert "Invalid session_id format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_issue_ws_token_invalid_session_id_format_returns_400(
        self, mock_request
    ):
        """無効なセッションID形式の場合に400エラーを返すことを確認する。"""
        # Arrange
        mock_request.path_params = {"session_id": "invalid-format"}

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await issue_ws_token(mock_request)

        assert exc_info.value.status_code == 400
        assert "Invalid session_id format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_issue_ws_token_session_not_found_returns_404(self, mock_request):
        """セッションが存在しない場合に404エラーを返すことを確認する。"""
        # Arrange
        mock_request.path_params = {"session_id": "agent-0001"}

        with (
            patch("gateway.api.terminal.anyio.to_thread.run_sync") as mock_run_sync,
        ):
            mock_run_sync.return_value = False

            # Act & Assert
            with pytest.raises(HTTPException) as exc_info:
                await issue_ws_token(mock_request)

            assert exc_info.value.status_code == 404
            assert "Session not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_issue_ws_token_success_returns_200(self, mock_request):
        """正常なリクエストで200レスポンスを返すことを確認する。"""
        # Arrange
        mock_request.path_params = {"session_id": "agent-0001"}
        test_token = "test_ws_token_32_bytes_or_more"

        with (
            patch("gateway.api.terminal.anyio.to_thread.run_sync") as mock_run_sync,
            patch("gateway.api.terminal.terminal_ws_token_store") as mock_store,
            patch("gateway.api.terminal.get_config") as mock_get_config,
        ):
            mock_run_sync.return_value = True
            mock_store.issue = AsyncMock(return_value=test_token)
            mock_config = MagicMock()
            mock_config.terminal_ws_token_ttl_seconds = 60
            mock_get_config.return_value = mock_config
            # Act
            response = await issue_ws_token(mock_request)

            # Assert
            assert response.status_code == 200
            body = response.body.decode()
            result = json.loads(body)
            assert result["ws_token"] == test_token
            assert result["expires_in_seconds"] == 60

    @pytest.mark.asyncio
    async def test_issue_ws_token_calls_store_with_correct_session_id(
        self, mock_request
    ):
        """トークンストアが正しいセッションIDで呼び出されることを確認する。"""
        # Arrange
        mock_request.path_params = {"session_id": "agent-0001"}
        test_token = "test_ws_token_32_bytes_or_more"

        with (
            patch("gateway.api.terminal.anyio.to_thread.run_sync") as mock_run_sync,
            patch("gateway.api.terminal.terminal_ws_token_store") as mock_store,
            patch("gateway.api.terminal.get_config") as mock_get_config,
        ):
            mock_run_sync.return_value = True
            mock_store.issue = AsyncMock(return_value=test_token)
            mock_config = MagicMock()
            mock_config.terminal_ws_token_ttl_seconds = 60
            mock_get_config.return_value = mock_config
            # Act
            await issue_ws_token(mock_request)

            # Assert
            mock_store.issue.assert_called_once_with("agent-0001", 60)

    @pytest.mark.asyncio
    async def test_issue_ws_token_valid_session_id_formats(self, mock_request):
        """有効なセッションID形式を確認する。"""
        # Arrange
        valid_session_ids = ["agent-0000", "agent-0001", "agent-9999"]

        with (
            patch("gateway.api.terminal.anyio.to_thread.run_sync") as mock_run_sync,
            patch("gateway.api.terminal.terminal_ws_token_store") as mock_store,
            patch("gateway.api.terminal.get_config") as mock_get_config,
        ):
            mock_run_sync.return_value = True
            mock_store.issue = AsyncMock(return_value="test_token")
            mock_config = MagicMock()
            mock_config.terminal_ws_token_ttl_seconds = 60
            mock_get_config.return_value = mock_config
            for session_id in valid_session_ids:
                # Arrange
                mock_request.path_params = {"session_id": session_id}

                # Act - 例外が発生しないことを確認
                # （セッション存在チェック後の処理まで進めるため、トークン発行もモック）
                response = await issue_ws_token(mock_request)

                # Assert
                assert response.status_code == 200
