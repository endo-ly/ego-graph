"""PTYマネージャーの単体テスト。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.services.pty_manager import (
    TUI_WHEEL_SENSITIVITY_FACTOR,
    PaneScrollContext,
    TmuxAttachManager,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def session_id():
    """テスト用セッションID。"""
    return "agent-0001"


@pytest.fixture
def pty_manager(session_id):
    """テスト用PTYマネージャー。"""
    return TmuxAttachManager(session_id)


# ============================================================================
# TmuxAttachManager初期化テスト
# ============================================================================


class TestTmuxAttachManagerInit:
    """TmuxAttachManager初期化のテスト。"""

    def test_init_with_session_id(self, pty_manager, session_id):
        """セッションIDで初期化されることを確認する。"""
        # Assert
        assert pty_manager.session_id == session_id
        assert not pty_manager.is_attached


# ============================================================================
# attach_sessionテスト
# ============================================================================


class TestAttachSession:
    """attach_sessionメソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_attach_session_success(self, pty_manager):
        """セッションへのattachが成功することを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None

        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close"),
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl"),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ),
        ):
            await pty_manager.attach_session()

            assert pty_manager.is_attached
            assert pty_manager._master_fd == 10

    @pytest.mark.asyncio
    async def test_attach_session_already_attached(self, pty_manager):
        """既にattach中の場合はエラーになることを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None

        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close"),
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl"),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ),
        ):
            await pty_manager.attach_session()

            with pytest.raises(RuntimeError, match="Already attached"):
                await pty_manager.attach_session()

    @pytest.mark.asyncio
    async def test_attach_session_launches_tmux_with_pty(self, pty_manager):
        """tmux attach がPTYで起動されることを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None

        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close"),
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl"),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ) as mock_exec,
        ):
            await pty_manager.attach_session()

            assert mock_exec.call_count >= 1
            args = mock_exec.call_args_list[0].args
            kwargs = mock_exec.call_args_list[0].kwargs
            assert args[:4] == ("tmux", "attach", "-t", "=agent-0001")
            assert kwargs["stdin"] == 11
            assert kwargs["stdout"] == 11
            assert kwargs["stderr"] == 11
            assert callable(kwargs["preexec_fn"])
            assert kwargs["env"]["TERM"] == "xterm-256color"

    @pytest.mark.asyncio
    async def test_attach_session_fails_on_openpty_error(self, pty_manager):
        """PTY作成失敗時に例外を送出することを確認する。"""
        with patch(
            "gateway.services.pty_manager.pty.openpty",
            side_effect=OSError("openpty failed"),
        ):
            with pytest.raises(OSError, match="openpty failed"):
                await pty_manager.attach_session()


# ============================================================================
# detach_sessionテスト
# ============================================================================


class TestDetachSession:
    """detach_sessionメソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_detach_session_when_not_attached(self, pty_manager):
        """attachしていない状態でのdetachが安全に完了することを確認する。"""
        # Arrange
        assert not pty_manager.is_attached

        # Act - エラーが発生しないことを確認
        await pty_manager.detach_session()

        # Assert
        assert not pty_manager.is_attached

    @pytest.mark.asyncio
    async def test_detach_session_terminates_process(self, pty_manager):
        """detach時にプロセスが終了することを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.wait = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_exit_copy_mode = AsyncMock()

        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close") as mock_close,
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl"),
            patch.object(
                pty_manager,
                "_exit_copy_mode_if_needed",
                new=mock_exit_copy_mode,
            ),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ),
        ):
            await pty_manager.attach_session()
            assert pty_manager.is_attached

            await pty_manager.detach_session()

            assert not pty_manager.is_attached
            mock_process.terminate.assert_called_once()
            mock_exit_copy_mode.assert_awaited_once()
            mock_close.assert_any_call(10)


# ============================================================================
# write_inputテスト
# ============================================================================


class TestWriteInput:
    """write_inputメソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_write_input_success(self, pty_manager):
        """入力書き込みが成功することを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_exit_copy_mode = AsyncMock()

        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close"),
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl"),
            patch.object(
                pty_manager,
                "_exit_copy_mode_if_needed",
                new=mock_exit_copy_mode,
            ),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ),
            patch(
                "gateway.services.pty_manager.os.write", return_value=10
            ) as mock_write,
        ):
            await pty_manager.attach_session()

            test_data = b"test input"
            await pty_manager.write_input(test_data)

            mock_exit_copy_mode.assert_awaited_once()
            mock_write.assert_called_once_with(10, test_data)

    @pytest.mark.asyncio
    async def test_write_input_when_not_attached_raises_error(self, pty_manager):
        """attachしていない状態で書き込みがエラーになることを確認する。"""
        # Arrange
        assert not pty_manager.is_attached

        # Act & Assert
        with pytest.raises(RuntimeError, match="Not attached"):
            await pty_manager.write_input(b"test")


# ============================================================================
# read_outputテスト
# ============================================================================


class TestReadOutput:
    """read_outputメソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_read_output_success(self, pty_manager):
        """出力読み込みが成功することを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None

        test_data = b"test output"
        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close"),
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl"),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ),
            patch(
                "gateway.services.pty_manager.os.read", return_value=test_data
            ) as mock_read,
        ):
            await pty_manager.attach_session()

            result = await pty_manager.read_output()

            assert result == test_data
            mock_read.assert_called_once_with(10, 4096)

    @pytest.mark.asyncio
    async def test_read_output_custom_buffer_size(self, pty_manager):
        """カスタムバッファサイズで読み込めることを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None

        test_data = b"test output"
        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close"),
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl"),
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ),
            patch(
                "gateway.services.pty_manager.os.read", return_value=test_data
            ) as mock_read,
        ):
            await pty_manager.attach_session()

            custom_size = 1024
            result = await pty_manager.read_output(custom_size)

            assert result == test_data
            mock_read.assert_called_once_with(10, custom_size)

    @pytest.mark.asyncio
    async def test_read_output_when_not_attached_raises_error(self, pty_manager):
        """attachしていない状態で読み込みがエラーになることを確認する。"""
        # Arrange
        assert not pty_manager.is_attached

        # Act & Assert
        with pytest.raises(RuntimeError, match="Not attached"):
            await pty_manager.read_output()


# ============================================================================
# resize_windowテスト
# ============================================================================


class TestResizeWindow:
    """resize_windowメソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_resize_window_success(self, pty_manager):
        """tmux resize-window コマンドが成功することを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
        ) as mock_exec:
            await pty_manager.resize_window(cols=120, rows=40)

            mock_exec.assert_called_once_with(
                "tmux",
                "resize-window",
                "-t",
                "agent-0001",
                "-x",
                "120",
                "-y",
                "40",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    @pytest.mark.asyncio
    async def test_resize_window_updates_attached_pty_size(self, pty_manager):
        """attach中はPTYサイズを直接更新することを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = None

        with (
            patch("gateway.services.pty_manager.pty.openpty", return_value=(10, 11)),
            patch("gateway.services.pty_manager.os.close"),
            patch("gateway.services.pty_manager.os.set_blocking"),
            patch("gateway.services.pty_manager.fcntl.ioctl") as mock_ioctl,
            patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=mock_process),
            ) as mock_exec,
        ):
            await pty_manager.attach_session()
            mock_exec.reset_mock()
            mock_ioctl.reset_mock()

            await pty_manager.resize_window(cols=120, rows=40)

            mock_exec.assert_not_called()
            mock_ioctl.assert_called_once()

    @pytest.mark.asyncio
    async def test_resize_window_raises_on_failure(self, pty_manager):
        """tmux resize-window 失敗時に例外を送出することを確認する。"""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"failed"))

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
        ):
            with pytest.raises(RuntimeError, match="Failed to resize tmux window"):
                await pty_manager.resize_window(cols=120, rows=40)


class TestScrollHistory:
    """scroll_historyメソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_scroll_history_up_enters_copy_mode_and_scrolls(self, pty_manager):
        enter_process = MagicMock()
        enter_process.returncode = 0
        enter_process.communicate = AsyncMock(return_value=(b"", b""))
        scroll_process = MagicMock()
        scroll_process.returncode = 0
        scroll_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[enter_process, scroll_process]),
        ) as mock_exec:
            await pty_manager.scroll_history(-3)

            assert mock_exec.call_args_list[0].args == (
                "tmux",
                "copy-mode",
                "-e",
                "-t",
                "agent-0001",
            )
            assert mock_exec.call_args_list[1].args == (
                "tmux",
                "send-keys",
                "-t",
                "agent-0001",
                "-X",
                "-N",
                "3",
                "scroll-up",
            )

    @pytest.mark.asyncio
    async def test_scroll_history_down_scrolls_only_in_copy_mode(self, pty_manager):
        status_process = MagicMock()
        status_process.returncode = 0
        status_process.communicate = AsyncMock(return_value=(b"1\n", b""))
        scroll_process = MagicMock()
        scroll_process.returncode = 0
        scroll_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[status_process, scroll_process]),
        ) as mock_exec:
            await pty_manager.scroll_history(2)

            assert mock_exec.call_args_list[0].args == (
                "tmux",
                "display-message",
                "-p",
                "-t",
                "agent-0001",
                "#{pane_in_mode}",
            )
            assert mock_exec.call_args_list[1].args == (
                "tmux",
                "send-keys",
                "-t",
                "agent-0001",
                "-X",
                "-N",
                "2",
                "scroll-down",
            )

    @pytest.mark.asyncio
    async def test_scroll_history_down_noops_outside_copy_mode(self, pty_manager):
        status_process = MagicMock()
        status_process.returncode = 0
        status_process.communicate = AsyncMock(return_value=(b"0\n", b""))

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=status_process),
        ) as mock_exec:
            await pty_manager.scroll_history(2)

            mock_exec.assert_called_once_with(
                "tmux",
                "display-message",
                "-p",
                "-t",
                "agent-0001",
                "#{pane_in_mode}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    @pytest.mark.asyncio
    async def test_scroll_history_rejects_out_of_range(self, pty_manager):
        with pytest.raises(ValueError, match="lines must be between"):
            await pty_manager.scroll_history(21)

    @pytest.mark.asyncio
    async def test_exit_copy_mode_if_needed_sends_cancel(self, pty_manager):
        status_process = MagicMock()
        status_process.returncode = 0
        status_process.communicate = AsyncMock(return_value=(b"1\n", b""))
        cancel_process = MagicMock()
        cancel_process.returncode = 0
        cancel_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[status_process, cancel_process]),
        ) as mock_exec:
            await pty_manager._exit_copy_mode_if_needed()

            assert mock_exec.call_args_list[1].args == (
                "tmux",
                "send-keys",
                "-t",
                "agent-0001",
                "-X",
                "cancel",
            )


class TestRouteScroll:
    """route_scrollメソッドのテスト。"""

    @pytest.mark.asyncio
    async def test_route_scroll_falls_back_to_history_when_context_missing(
        self, pty_manager
    ):
        """tmux状態が取得できない場合は従来の履歴スクロールへ戻ることを確認する。"""
        pty_manager._get_pane_scroll_context = AsyncMock(return_value=None)
        pty_manager.scroll_history = AsyncMock()

        await pty_manager.route_scroll(-3)

        pty_manager.scroll_history.assert_awaited_once_with(-3)

    @pytest.mark.asyncio
    async def test_route_scroll_uses_history_in_copy_mode(self, pty_manager):
        """copy-mode中は履歴スクロールを優先することを確認する。"""
        context = PaneScrollContext(
            pane_in_mode=True,
            alternate_on=False,
            mouse_any_flag=False,
            pane_width=80,
            pane_height=24,
        )
        pty_manager._get_pane_scroll_context = AsyncMock(return_value=context)
        pty_manager.scroll_history = AsyncMock()
        pty_manager._send_mouse_wheel = AsyncMock()

        await pty_manager.route_scroll(2)

        pty_manager.scroll_history.assert_awaited_once_with(2)
        pty_manager._send_mouse_wheel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_scroll_passthroughs_wheel_when_mouse_mode_enabled(
        self, pty_manager
    ):
        """mouse_any_flagが立っている場合はTUIへホイール入力を渡すことを確認する。"""
        context = PaneScrollContext(
            pane_in_mode=False,
            alternate_on=True,
            mouse_any_flag=True,
            pane_width=79,
            pane_height=55,
        )
        pty_manager._get_pane_scroll_context = AsyncMock(return_value=context)
        pty_manager.scroll_history = AsyncMock()
        pty_manager._send_mouse_wheel = AsyncMock()

        await pty_manager.route_scroll(int(-2 / TUI_WHEEL_SENSITIVITY_FACTOR))

        pty_manager._send_mouse_wheel.assert_awaited_once_with(-2, context)
        pty_manager.scroll_history.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_scroll_accumulates_tui_fractional_steps(self, pty_manager):
        """TUI 向け感度調整の端数が累積されることを確認する。"""
        context = PaneScrollContext(
            pane_in_mode=False,
            alternate_on=True,
            mouse_any_flag=True,
            pane_width=79,
            pane_height=55,
        )
        pty_manager._get_pane_scroll_context = AsyncMock(return_value=context)
        pty_manager._send_mouse_wheel = AsyncMock()

        await pty_manager.route_scroll(-1)
        pty_manager._send_mouse_wheel.assert_not_awaited()

        await pty_manager.route_scroll(-1)
        pty_manager._send_mouse_wheel.assert_awaited_once_with(-1, context)

    @pytest.mark.asyncio
    async def test_route_scroll_ignores_alternate_screen_without_mouse_support(
        self, pty_manager
    ):
        """alternate screenだがmouse未対応の場合は外側履歴へ落ちないことを確認する。"""
        context = PaneScrollContext(
            pane_in_mode=False,
            alternate_on=True,
            mouse_any_flag=False,
            pane_width=80,
            pane_height=24,
        )
        pty_manager._get_pane_scroll_context = AsyncMock(return_value=context)
        pty_manager.scroll_history = AsyncMock()
        pty_manager._send_mouse_wheel = AsyncMock()

        await pty_manager.route_scroll(-1)

        pty_manager.scroll_history.assert_not_awaited()
        pty_manager._send_mouse_wheel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_scroll_resets_tui_remainder_when_leaving_passthrough(
        self, pty_manager
    ):
        """TUI を抜けたら端数が持ち越されないことを確認する。"""
        passthrough_context = PaneScrollContext(
            pane_in_mode=False,
            alternate_on=True,
            mouse_any_flag=True,
            pane_width=79,
            pane_height=55,
        )
        normal_context = PaneScrollContext(
            pane_in_mode=False,
            alternate_on=False,
            mouse_any_flag=False,
            pane_width=79,
            pane_height=55,
        )
        pty_manager._get_pane_scroll_context = AsyncMock(
            side_effect=[passthrough_context, normal_context, passthrough_context]
        )
        pty_manager.scroll_history = AsyncMock()
        pty_manager._send_mouse_wheel = AsyncMock()

        await pty_manager.route_scroll(-1)
        await pty_manager.route_scroll(-1)
        await pty_manager.route_scroll(-1)

        pty_manager.scroll_history.assert_awaited_once_with(-1)
        pty_manager._send_mouse_wheel.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_mouse_wheel_writes_centered_sgr_sequence(self, pty_manager):
        """ホイール入力が中央座標のSGRシーケンスとしてPTYへ書かれることを確認する。"""
        context = PaneScrollContext(
            pane_in_mode=False,
            alternate_on=True,
            mouse_any_flag=True,
            pane_width=79,
            pane_height=55,
        )
        pty_manager._attached = True
        pty_manager._master_fd = 10
        pty_manager._write_master = AsyncMock()

        await pty_manager._send_mouse_wheel(-2, context)

        pty_manager._write_master.assert_awaited_once_with(
            b"\x1b[<64;40;28M\x1b[<64;40;28M"
        )

    def test_parse_pane_scroll_context_uses_default_size_on_invalid_values(
        self, pty_manager
    ):
        """paneサイズが壊れていても既定サイズへfallbackできることを確認する。"""
        context = pty_manager._parse_pane_scroll_context("1,0,1,x,y")

        assert context == PaneScrollContext(
            pane_in_mode=True,
            alternate_on=False,
            mouse_any_flag=True,
            pane_width=80,
            pane_height=24,
        )

    def test_adjust_tui_wheel_steps_applies_sensitivity_factor(self, pty_manager):
        """TUI 向け wheel step が感度係数で間引かれることを確認する。"""
        assert pty_manager._adjust_tui_wheel_steps(-1) == 0
        assert pty_manager._adjust_tui_wheel_steps(-1) == -1


# ============================================================================
# プロパティアクセステスト
# ============================================================================


class TestPropertyAccess:
    """プロパティアクセスのテスト。"""

    @pytest.mark.asyncio
    async def test_stdin_property_when_not_attached_raises_error(self, pty_manager):
        """attachしていない状態でstdinアクセスがエラーになることを確認する。"""
        # Act & Assert
        with pytest.raises(RuntimeError, match="Not attached"):
            _ = pty_manager.stdin

    @pytest.mark.asyncio
    async def test_stdout_property_when_not_attached_raises_error(self, pty_manager):
        """attachしていない状態でstdoutアクセスがエラーになることを確認する。"""
        # Act & Assert
        with pytest.raises(RuntimeError, match="Not attached"):
            _ = pty_manager.stdout
