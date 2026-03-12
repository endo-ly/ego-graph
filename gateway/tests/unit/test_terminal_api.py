"""Terminal API の単体テスト。

セッション一覧 API とプレビュー機能のテストを行います
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.exceptions import HTTPException

from gateway.api.terminal import (
    _extract_preview_lines,
    get_session,
    get_sessions,
)
from gateway.infrastructure.tmux import Session
from datetime import datetime, timezone


@pytest.fixture
def mock_request():
    """テスト用リクエスト."""
    request = MagicMock()
    request.headers = {"X-API-Key": "valid_api_key_32_bytes_or_more"}
    request.path_params = {}
    return request


@pytest.fixture
def mock_session():
    """テスト用 tmux セッション."""
    now = datetime.now(tz=timezone.utc)
    return Session(
        name="agent-0001",
        last_activity=now,
        created_at=now,
    )


# ============================================================================
# _extract_preview_lines 関数のテスト
# ============================================================================


class TestExtractPreviewLines:
    """_extract_preview_lines 関数のテスト."""

    def test_returns_empty_for_empty_text(self):
        """空テキストの場合に空リストを返すことを確認する."""
        preview_available, preview_lines = _extract_preview_lines("")
        assert preview_available is False
        assert preview_lines == []

    def test_removes_ansi_escape_sequences(self):
        """ANSI エスケープシーケンスを除去することを確認する."""
        text = "\x1b[31mError message\x1b[0m\nNormal text"
        preview_available, preview_lines = _extract_preview_lines(text)
        assert preview_available is True
        assert len(preview_lines) == 2
        assert "Error message" in preview_lines[0]
        assert "Normal text" in preview_lines[1]
        assert "\x1b" not in preview_lines[0]

    def test_removes_control_characters(self):
        """制御文字を除去することを確認する."""
        text = "Line 1\x00\x01\x02\nLine 2\x7f"
        preview_available, preview_lines = _extract_preview_lines(text)
        assert preview_available is True
        assert len(preview_lines) == 2
        assert preview_lines[0] == "Line 1"
        assert preview_lines[1] == "Line 2"

    def test_filters_empty_lines(self):
        """空行をフィルタリングすることを確認する."""
        text = "Line 1\n\n\nLine 2\n   \nLine 3"
        preview_available, preview_lines = _extract_preview_lines(text)
        assert preview_available is True
        assert len(preview_lines) == 3
        assert preview_lines[0] == "Line 1"
        assert preview_lines[1] == "Line 2"
        assert preview_lines[2] == "Line 3"

    def test_returns_all_non_empty_lines(self):
        """空でない行をすべて返すことを確認する."""
        text = "\n".join([f"Line {i}" for i in range(10)])
        preview_available, preview_lines = _extract_preview_lines(text)
        assert preview_available is True
        assert len(preview_lines) == 10
        assert preview_lines[0] == "Line 0"
        assert preview_lines[9] == "Line 9"

    def test_returns_latest_lines(self):
        """最新の行を返すことを確認する."""
        text = "First line\nMiddle line\nLast line"
        preview_available, preview_lines = _extract_preview_lines(text)
        assert preview_available is True
        assert len(preview_lines) == 3
        assert preview_lines[2] == "Last line"

    def test_handles_whitespace_only_lines(self):
        """空白のみの行を空行として扱うことを確認する."""
        text = "Line 1\n   \n\t\nLine 2"
        preview_available, preview_lines = _extract_preview_lines(text)
        assert preview_available is True
        assert len(preview_lines) == 2
        assert preview_lines[0] == "Line 1"
        assert preview_lines[1] == "Line 2"

    def test_preserves_tabs_and_spaces_in_content(self):
        """コンテンツ内のタブとスペースを保持することを確認する."""
        text = "Line 1\tColumn 2\n  Indented line  "
        preview_available, preview_lines = _extract_preview_lines(text)
        assert preview_available is True
        assert len(preview_lines) == 2
        assert "\t" in preview_lines[0] or "Column 2" in preview_lines[0]


# ============================================================================
# _build_session_response 関数のテスト
# ============================================================================


class TestBuildSessionResponse:
    """_build_session_response 関数のテスト."""

    @pytest.mark.asyncio
    async def test_includes_preview_fields(self, mock_session):
        """プレビューフィールドを含むことを確認する."""
        with (
            patch("gateway.api.terminal.verify_gateway_token"),
            patch("gateway.api.terminal.TmuxAttachManager") as mock_manager_class,
        ):
            # スナップショット取得をモック
            mock_manager = MagicMock()
            mock_manager.capture_snapshot = AsyncMock(
                return_value=b"Line 1\nLine 2\nLine 3"
            )
            mock_manager_class.return_value = mock_manager

            from gateway.api.terminal import _build_session_response

            response = await _build_session_response("agent-0001", mock_session)

            assert "preview_available" in response
            assert "preview_lines" in response
            assert response["session_id"] == "agent-0001"
            assert response["name"] == "agent-0001"

    @pytest.mark.asyncio
    async def test_falls_back_on_snapshot_failure(self, mock_session):
        """スナップショット取得失敗時にフォールバックすることを確認する."""
        with (
            patch("gateway.api.terminal.verify_gateway_token"),
            patch("gateway.api.terminal.TmuxAttachManager") as mock_manager_class,
        ):
            # スナップショット取得が失敗するようにモック
            mock_manager = MagicMock()
            mock_manager.capture_snapshot = AsyncMock(
                side_effect=RuntimeError("capture failed")
            )
            mock_manager_class.return_value = mock_manager

            from gateway.api.terminal import _build_session_response

            response = await _build_session_response("agent-0001", mock_session)

            # フォールバック値が設定されていることを確認
            assert response["preview_available"] is False
            assert response["preview_lines"] == []

    @pytest.mark.asyncio
    async def test_sanitizes_preview_content(self, mock_session):
        """プレビューコンテンツをサニタイズすることを確認する."""
        with (
            patch("gateway.api.terminal.verify_gateway_token"),
            patch("gateway.api.terminal.TmuxAttachManager") as mock_manager_class,
        ):
            # ANSI エスケープシーケンスを含むスナップショット
            snapshot_with_ansi = b"\x1b[31mError\x1b[0m\nNormal text"
            mock_manager = MagicMock()
            mock_manager.capture_snapshot = AsyncMock(return_value=snapshot_with_ansi)
            mock_manager_class.return_value = mock_manager

            from gateway.api.terminal import _build_session_response

            response = await _build_session_response("agent-0001", mock_session)

            assert response["preview_available"] is True
            assert len(response["preview_lines"]) == 2
            # ANSI シーケンスが除去されていることを確認
            assert "\x1b" not in response["preview_lines"][0]
            assert "Error" in response["preview_lines"][0]

    @pytest.mark.asyncio
    async def test_returns_all_preview_lines(self, mock_session):
        """プレビュー行を切り詰めずに返すことを確認する."""
        with (
            patch("gateway.api.terminal.verify_gateway_token"),
            patch("gateway.api.terminal.TmuxAttachManager") as mock_manager_class,
        ):
            # 10行のスナップショット
            snapshot_with_many_lines = b"\n".join(
                [f"Line {i}".encode() for i in range(10)]
            )
            mock_manager = MagicMock()
            mock_manager.capture_snapshot = AsyncMock(
                return_value=snapshot_with_many_lines
            )
            mock_manager_class.return_value = mock_manager

            from gateway.api.terminal import _build_session_response

            response = await _build_session_response("agent-0001", mock_session)

            assert response["preview_available"] is True
            assert len(response["preview_lines"]) == 10
            assert response["preview_lines"][0] == "Line 0"
            assert response["preview_lines"][9] == "Line 9"


# ============================================================================
# get_sessions エンドポイントのテスト
# ============================================================================


class TestGetSessions:
    """get_sessions エンドポイントのテスト."""

    @pytest.mark.asyncio
    async def test_returns_sessions_with_previews(self, mock_request):
        """プレビュー付きでセッション一覧を返すことを確認する."""
        with (
            patch("gateway.api.terminal.verify_gateway_token"),
            patch("gateway.api.terminal.anyio.to_thread.run_sync") as mock_run_sync,
            patch("gateway.api.terminal.TmuxAttachManager") as mock_manager_class,
        ):
            # モックの設定
            now = datetime.now(tz=timezone.utc)
            mock_sessions = [
                Session(name="agent-0001", last_activity=now, created_at=now),
            ]
            mock_run_sync.return_value = mock_sessions
            mock_manager = MagicMock()
            mock_manager.capture_snapshot = AsyncMock(
                return_value=b"$ echo hello\nhello\n$ "
            )
            mock_manager_class.return_value = mock_manager

            response = await get_sessions(mock_request)
            body = json.loads(response.body.decode())

            assert response.status_code == 200
            assert body["count"] == 1
            assert len(body["sessions"]) == 1
            session = body["sessions"][0]
            assert session["session_id"] == "agent-0001"
            assert "preview_available" in session
            assert "preview_lines" in session


# ============================================================================
# get_session エンドポイントのテスト
# ============================================================================


class TestGetSession:
    """get_session エンドポイントのテスト."""

    @pytest.mark.asyncio
    async def test_returns_single_session_with_preview(self, mock_request):
        """単一セッションをプレビュー付きで返すことを確認する."""
        mock_request.path_params = {"session_id": "agent-0001"}

        with (
            patch("gateway.api.terminal.verify_gateway_token"),
            patch("gateway.api.terminal.anyio.to_thread.run_sync") as mock_run_sync,
            patch("gateway.api.terminal.TmuxAttachManager") as mock_manager_class,
        ):
            # モックの設定
            now = datetime.now(tz=timezone.utc)
            mock_sessions = [
                Session(name="agent-0001", last_activity=now, created_at=now),
            ]
            mock_run_sync.return_value = mock_sessions
            mock_manager = MagicMock()
            mock_manager.capture_snapshot = AsyncMock(
                return_value=b"Preview content\nLine 2"
            )
            mock_manager_class.return_value = mock_manager

            response = await get_session(mock_request)
            body = json.loads(response.body.decode())

            assert response.status_code == 200
            assert body["session_id"] == "agent-0001"
            assert "preview_available" in body
            assert "preview_lines" in body
