"""PTYプロセスのライフサイクル管理。

tmuxセッションへのattach/detachを担当する。
"""

import asyncio
import errno
import fcntl
import logging
import os
import pty
import re
import struct
import termios
import time
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

# セッションIDの検証パターン（英数字とハイフンのみ許可）
SESSION_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9-]+$")
TMUX_CAPTURE_TIMEOUT_SECONDS: Final = 2.0
TMUX_CURSOR_TIMEOUT_SECONDS: Final = 1.0
TMUX_ATTACH_TERM: Final = "xterm-256color"
DEFAULT_PTY_COLS: Final = 80
DEFAULT_PTY_ROWS: Final = 24
MAX_SCROLL_LINES: Final = 20
SCROLL_CONTEXT_CACHE_TTL_SECONDS: Final = 0.1
TUI_WHEEL_SENSITIVITY_FACTOR: Final = 0.3
TMUX_SCROLL_CONTEXT_FORMAT: Final = (
    "#{pane_in_mode},#{alternate_on},#{mouse_any_flag},#{pane_width},#{pane_height}"
)
MOUSE_WHEEL_UP_BUTTON: Final = 64
MOUSE_WHEEL_DOWN_BUTTON: Final = 65


@dataclass(frozen=True)
class PaneScrollContext:
    """スクロール分岐に必要な tmux pane 状態。"""

    pane_in_mode: bool
    alternate_on: bool
    mouse_any_flag: bool
    pane_width: int
    pane_height: int

    @property
    def should_passthrough_wheel(self) -> bool:
        """アプリへホイール入力を素通しすべきかどうか。"""
        return self.mouse_any_flag and not self.pane_in_mode


class TmuxAttachManager:
    """tmuxセッションへのattachプロセスを管理する。

    WebSocket接続ごとに1つのattachプロセスを作成し、
    接続切断時にプロセスを終了する。
    """

    def __init__(self, session_id: str) -> None:
        """TmuxAttachManagerを初期化する。

        Args:
            session_id: tmuxセッションID (例: agent-0001)

        Raises:
            ValueError: セッションIDに不正な文字が含まれる場合
        """
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError(
                f"Invalid session_id format: {session_id}. "
                "Only alphanumeric characters and hyphens are allowed."
            )
        self._session_id = session_id
        self._tmux_attach_target = f"={session_id}"
        self._tmux_session_target = session_id
        self._process: asyncio.subprocess.Process | None = None
        self._stdin: asyncio.StreamWriter | None = None
        self._stdout: asyncio.StreamReader | None = None
        self._stderr: asyncio.StreamReader | None = None
        self._master_fd: int | None = None
        self._attached = False
        self._scroll_context_cache: tuple[float, PaneScrollContext] | None = None
        self._tui_wheel_remainder = 0.0

    @property
    def session_id(self) -> str:
        """tmuxセッションIDを取得する。"""
        return self._session_id

    @property
    def is_attached(self) -> bool:
        """attach中かどうかを取得する。"""
        return self._attached

    @property
    def stdin(self) -> asyncio.StreamWriter:
        """標準入力ストリームを取得する。

        Returns:
            標準入力ストリーム

        Raises:
            RuntimeError: attachされていない場合
        """
        if not self._attached or self._stdin is None:
            raise RuntimeError("Not attached to session")
        return self._stdin

    @property
    def stdout(self) -> asyncio.StreamReader:
        """標準出力ストリームを取得する。

        Returns:
            標準出力ストリーム

        Raises:
            RuntimeError: attachされていない場合
        """
        if not self._attached or self._stdout is None:
            raise RuntimeError("Not attached to session")
        return self._stdout

    async def attach_session(self) -> None:
        """tmuxセッションにattachする。

        `tmux attach -t <session_id>` を非同期プロセスとして実行する。

        Raises:
            RuntimeError: 既にattach中の場合
            asyncio.TimeoutError: attach開始がタイムアウトした場合
        """
        if self._attached:
            raise RuntimeError(f"Already attached to session {self._session_id}")

        logger.info("Attaching to session: %s", self._session_id)
        process = None  # 一時変数でプロセスを保持
        master_fd: int | None = None
        slave_fd: int | None = None

        try:
            # tmux attach はTTYが必要なため、明示的にPTYを作成して接続する。
            master_fd, slave_fd = pty.openpty()
            self._set_winsize(master_fd, DEFAULT_PTY_COLS, DEFAULT_PTY_ROWS)

            env = {**os.environ, "TERM": TMUX_ATTACH_TERM}

            def _child_setup() -> None:
                os.setsid()
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

            process = await asyncio.create_subprocess_exec(
                "tmux",
                "attach",
                "-t",
                self._tmux_attach_target,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                preexec_fn=_child_setup,
            )
            os.close(slave_fd)
            slave_fd = None
            os.set_blocking(master_fd, False)

            self._process = process
            self._master_fd = master_fd
            self._stdin = process.stdin
            self._stdout = process.stdout
            self._stderr = process.stderr
            self._attached = True
            await self._configure_session_for_web_client()

            logger.info("Successfully attached to session: %s", self._session_id)

        except Exception as e:
            logger.error("Failed to attach to session %s: %s", self._session_id, e)
            # プロセスが作成されている場合は終了させる
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            if slave_fd is not None:
                try:
                    os.close(slave_fd)
                except OSError:
                    pass
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
            raise

    async def _configure_session_for_web_client(self) -> None:
        """Web表示向けにtmuxの装飾行を無効化する。"""
        commands = [
            [
                "tmux",
                "set-option",
                "-q",
                "-t",
                self._tmux_session_target,
                "status",
                "off",
            ],
            [
                "tmux",
                "set-window-option",
                "-q",
                "-t",
                self._tmux_session_target,
                "pane-border-status",
                "off",
            ],
        ]
        for cmd in commands:
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=TMUX_CAPTURE_TIMEOUT_SECONDS,
                )
            except Exception as e:
                logger.debug("Failed to configure tmux option %s: %s", cmd, e)

    async def detach_session(self) -> None:
        """tmuxセッションからdetachする。

        attachプロセスを終了する。tmuxセッション自体は保持される。
        """
        if not self._attached:
            return

        logger.info("Detaching from session: %s", self._session_id)

        try:
            await self._exit_copy_mode_if_needed()
        except Exception as e:
            logger.debug("Failed to exit copy mode before detach: %s", e)

        # プロセスを終了
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Process did not terminate gracefully, killing")
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.error("Error during process termination: %s", e)

        # ストリームをクローズ
        if self._stdin and not self._stdin.is_closing():
            self._stdin.close()
            try:
                await self._stdin.wait_closed()
            except Exception as e:
                logger.error("Error closing stdin: %s", e)
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError as e:
                logger.debug("Error closing master PTY fd: %s", e)

        # 状態をリセット
        self._process = None
        self._stdin = None
        self._stdout = None
        self._stderr = None
        self._master_fd = None
        self._attached = False

        logger.info("Successfully detached from session: %s", self._session_id)

    async def write_input(self, data: bytes) -> None:
        """端末に入力データを書き込む。

        Args:
            data: 入力データ

        Raises:
            RuntimeError: attachされていない場合
            OSError: 書き込みに失敗した場合
        """
        if not self._attached:
            raise RuntimeError("Not attached to session")

        try:
            await self._exit_copy_mode_if_needed()
            if self._master_fd is not None:
                await self._write_master(data)
                return

            if self._stdin is None or self._is_stream_closing(self._stdin):
                await self._send_keys_via_tmux(data)
                return

            self._stdin.write(data)
            await self._stdin.drain()
        except Exception as e:
            logger.warning(
                "Direct stdin write failed, falling back to tmux send-keys: %s", e
            )
            await self._send_keys_via_tmux(data)

    @staticmethod
    def _is_stream_closing(stream: asyncio.StreamWriter) -> bool:
        checker = getattr(stream, "is_closing", None)
        if not callable(checker):
            return False
        result = checker()
        return result if isinstance(result, bool) else False

    async def _send_keys_via_tmux(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="ignore")
        chunk: list[str] = []

        async def flush_chunk() -> None:
            if chunk:
                await self._run_tmux_send_keys(["-l", "".join(chunk)])
                chunk.clear()

        for char in text:
            if char in ("\r", "\n"):
                await flush_chunk()
                await self._run_tmux_send_keys(["Enter"])
            elif char in ("\b", "\x7f"):
                await flush_chunk()
                await self._run_tmux_send_keys(["BSpace"])
            elif char == "\t":
                await flush_chunk()
                await self._run_tmux_send_keys(["Tab"])
            else:
                chunk.append(char)

        await flush_chunk()

    async def _run_tmux_send_keys(self, args: list[str]) -> None:
        cmd = ["tmux", "send-keys", "-t", self._tmux_session_target, *args]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TMUX_CAPTURE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            process.kill()
            await process.wait()
            raise RuntimeError("tmux send-keys timed out") from e
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore").strip() or "unknown error"
            raise RuntimeError(f"Failed to send keys via tmux: {message}")

    async def scroll_history(self, lines: int) -> None:
        """tmux copy-mode の履歴をスクロールする。"""
        self._validate_scroll_lines(lines)
        if lines == 0:
            return

        if lines < 0:
            await self._enter_copy_mode()
            await self._run_tmux_copy_mode_command("scroll-up", abs(lines))
            return

        if await self._is_in_copy_mode():
            await self._run_tmux_copy_mode_command("scroll-down", lines)

    async def route_scroll(self, lines: int) -> None:
        """tmux 状態に応じて履歴スクロールか TUI ホイールへ振り分ける。"""
        self._validate_scroll_lines(lines)
        if lines == 0:
            return

        context = await self._get_pane_scroll_context()
        if context is None:
            self._reset_tui_wheel_remainder()
            await self.scroll_history(lines)
            return

        if context.pane_in_mode:
            self._reset_tui_wheel_remainder()
            await self.scroll_history(lines)
            return

        if context.should_passthrough_wheel:
            wheel_steps = self._adjust_tui_wheel_steps(lines)
            if wheel_steps == 0:
                return
            await self._send_mouse_wheel(wheel_steps, context)
            return

        if context.alternate_on:
            self._reset_tui_wheel_remainder()
            logger.debug(
                "Ignoring scroll for alternate screen without mouse support: "
                "session=%s",
                self._session_id,
            )
            return

        self._reset_tui_wheel_remainder()
        await self.scroll_history(lines)

    @staticmethod
    def _validate_scroll_lines(lines: int) -> None:
        """スクロール行数の妥当性を検証する。"""
        if not isinstance(lines, int):
            raise ValueError(f"lines must be an integer, got {lines}")
        if abs(lines) > MAX_SCROLL_LINES:
            raise ValueError(
                "lines must be between "
                f"{-MAX_SCROLL_LINES} and {MAX_SCROLL_LINES}, got {lines}"
            )

    async def _get_pane_scroll_context(self) -> PaneScrollContext | None:
        """スクロール分岐に必要な pane 状態を取得する。"""
        now = time.monotonic()
        if self._scroll_context_cache is not None:
            cached_at, cached_context = self._scroll_context_cache
            if now - cached_at <= SCROLL_CONTEXT_CACHE_TTL_SECONDS:
                return cached_context

        cmd = [
            "tmux",
            "display-message",
            "-p",
            "-t",
            self._tmux_session_target,
            TMUX_SCROLL_CONTEXT_FORMAT,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TMUX_CURSOR_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return None

        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore").strip() or "unknown error"
            logger.debug("Failed to capture tmux scroll context: %s", message)
            return None

        context = self._parse_pane_scroll_context(
            stdout.decode("utf-8", errors="ignore").strip()
        )
        if context is not None:
            self._scroll_context_cache = (now, context)
        return context

    @staticmethod
    def _parse_pane_scroll_context(raw: str) -> PaneScrollContext | None:
        """tmux format 出力を PaneScrollContext へ変換する。"""
        parts = raw.split(",")
        if len(parts) != 5:
            return None

        try:
            pane_width = max(int(parts[3]), 1)
        except ValueError:
            pane_width = DEFAULT_PTY_COLS

        try:
            pane_height = max(int(parts[4]), 1)
        except ValueError:
            pane_height = DEFAULT_PTY_ROWS

        return PaneScrollContext(
            pane_in_mode=parts[0] == "1",
            alternate_on=parts[1] == "1",
            mouse_any_flag=parts[2] == "1",
            pane_width=pane_width,
            pane_height=pane_height,
        )

    def _adjust_tui_wheel_steps(self, lines: int) -> int:
        """TUI 向け wheel step を間引きつつ端数を保持する。"""
        self._tui_wheel_remainder += lines * TUI_WHEEL_SENSITIVITY_FACTOR
        wheel_steps = int(self._tui_wheel_remainder)
        if wheel_steps == 0:
            return 0
        self._tui_wheel_remainder -= wheel_steps
        return wheel_steps

    def _reset_tui_wheel_remainder(self) -> None:
        """TUI 専用感度調整の端数をリセットする。"""
        self._tui_wheel_remainder = 0.0

    async def _send_mouse_wheel(
        self,
        lines: int,
        context: PaneScrollContext,
    ) -> None:
        """tmux attach PTY へホイール入力をそのまま流す。"""
        if not self._attached or self._master_fd is None:
            raise RuntimeError("Mouse wheel passthrough requires an attached PTY")

        button = MOUSE_WHEEL_UP_BUTTON if lines < 0 else MOUSE_WHEEL_DOWN_BUTTON
        col = max(1, (context.pane_width + 1) // 2)
        row = max(1, (context.pane_height + 1) // 2)
        sequence = f"\x1b[<{button};{col};{row}M".encode("ascii")
        await self._write_master(sequence * abs(lines))

    async def _exit_copy_mode_if_needed(self) -> None:
        if await self._is_in_copy_mode():
            await self._run_tmux_copy_mode_command("cancel")

    async def _enter_copy_mode(self) -> None:
        cmd = ["tmux", "copy-mode", "-e", "-t", self._tmux_session_target]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TMUX_CAPTURE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            process.kill()
            await process.wait()
            raise RuntimeError("tmux copy-mode timed out") from e
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore").strip() or "unknown error"
            raise RuntimeError(f"Failed to enter tmux copy mode: {message}")

    async def _is_in_copy_mode(self) -> bool:
        cmd = [
            "tmux",
            "display-message",
            "-p",
            "-t",
            self._tmux_session_target,
            "#{pane_in_mode}",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=TMUX_CURSOR_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False

        if process.returncode != 0:
            return False

        return stdout.decode("utf-8", errors="ignore").strip() == "1"

    async def _run_tmux_copy_mode_command(
        self,
        command: str,
        count: int | None = None,
    ) -> None:
        cmd = [
            "tmux",
            "send-keys",
            "-t",
            self._tmux_session_target,
            "-X",
            command,
        ]
        if count is not None:
            cmd[5:5] = ["-N", str(count)]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TMUX_CAPTURE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            process.kill()
            await process.wait()
            raise RuntimeError("tmux copy-mode send-keys timed out") from e
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore").strip() or "unknown error"
            raise RuntimeError(f"Failed to scroll tmux copy mode: {message}")

    async def read_output(self, n: int = 4096) -> bytes:
        """端末から出力データを読み込む。

        Args:
            n: 読み込む最大バイト数

        Returns:
            読み込んだデータ

        Raises:
            RuntimeError: attachされていない場合
        """
        if not self._attached:
            raise RuntimeError("Not attached to session")

        try:
            if self._master_fd is not None:
                return await self._read_master(n)
            if self._stdout is None:
                raise RuntimeError("Not attached to session")
            return await self._stdout.read(n)
        except Exception as e:
            logger.error("Failed to read output: %s", e)
            raise

    async def read_stderr(self, n: int = 4096) -> bytes:
        """標準エラーからデータを読み込む。

        Args:
            n: 読み込む最大バイト数

        Returns:
            読み込んだデータ

        Raises:
            RuntimeError: attachされていない場合
        """
        if not self._attached:
            raise RuntimeError("Not attached to session")
        if self._stderr is None:
            return b""

        try:
            return await self._stderr.read(n)
        except Exception as e:
            logger.error("Failed to read stderr: %s", e)
            raise

    @staticmethod
    def _set_winsize(
        fd: int,
        cols: int,
        rows: int,
    ) -> None:
        """PTYの画面サイズを設定する。"""
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def _wait_fd_readable(self, fd: int) -> None:
        """指定FDが読み取り可能になるまで待機する。"""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        def on_readable() -> None:
            if not future.done():
                future.set_result(None)

        loop.add_reader(fd, on_readable)
        try:
            await future
        finally:
            loop.remove_reader(fd)

    async def _wait_fd_writable(self, fd: int) -> None:
        """指定FDが書き込み可能になるまで待機する。"""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        def on_writable() -> None:
            if not future.done():
                future.set_result(None)

        loop.add_writer(fd, on_writable)
        try:
            await future
        finally:
            loop.remove_writer(fd)

    async def _read_master(self, n: int) -> bytes:
        """master PTYから非同期に読み込む。"""
        if self._master_fd is None:
            raise RuntimeError("Not attached to session")
        while True:
            try:
                return os.read(self._master_fd, n)
            except BlockingIOError:
                await self._wait_fd_readable(self._master_fd)
            except OSError as e:
                # PTYクローズ時はEIOになるためEOFとして扱う。
                if e.errno == errno.EIO:
                    return b""
                raise

    async def _write_master(self, data: bytes) -> None:
        """master PTYへ非同期に書き込む。"""
        if self._master_fd is None:
            raise RuntimeError("Not attached to session")
        remaining = data
        while remaining:
            try:
                written = os.write(self._master_fd, remaining)
                remaining = remaining[written:]
            except BlockingIOError:
                await self._wait_fd_writable(self._master_fd)

    async def resize_window(
        self,
        cols: int,
        rows: int,
    ) -> None:
        """tmux セッションのウィンドウサイズを変更する。

        Args:
            cols: 列数（正の整数）
            rows: 行数（正の整数）

        Raises:
            ValueError: colsまたはrowsが無効な場合
        """
        if not isinstance(cols, int) or cols <= 0:
            raise ValueError(f"cols must be a positive integer, got {cols}")
        if not isinstance(rows, int) or rows <= 0:
            raise ValueError(f"rows must be a positive integer, got {rows}")

        if self._attached and self._master_fd is not None:
            self._set_winsize(self._master_fd, cols, rows)
            return

        cmd = [
            "tmux",
            "resize-window",
            "-t",
            self._tmux_session_target,
            "-x",
            str(cols),
            "-y",
            str(rows),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore").strip() or "unknown error"
            raise RuntimeError(f"Failed to resize tmux window: {message}")

    async def capture_snapshot(self, include_escape_sequences: bool = False) -> bytes:
        """現在の tmux ペイン内容を取得する。"""
        cmd = ["tmux", "capture-pane", "-p"]
        if include_escape_sequences:
            cmd.append("-e")
        cmd.extend(["-S", "-200", "-t", self._tmux_session_target])
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TMUX_CAPTURE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            process.kill()
            await process.wait()
            raise RuntimeError("Failed to capture tmux snapshot: timeout") from e

        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore").strip() or "unknown error"
            raise RuntimeError(f"Failed to capture tmux snapshot: {message}")

        return stdout

    async def capture_cursor_info(self) -> tuple[int | None, int | None, int | None]:
        """現在の tmux カーソル座標と表示行数を取得する。"""
        cmd = [
            "tmux",
            "display-message",
            "-p",
            "-t",
            self._tmux_session_target,
            "#{cursor_x},#{cursor_y},#{pane_height}",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TMUX_CURSOR_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return (None, None, None)

        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore").strip() or "unknown error"
            logger.debug("Failed to capture tmux cursor info: %s", message)
            return (None, None, None)

        raw = stdout.decode("utf-8", errors="ignore").strip()
        parts = raw.split(",")
        if len(parts) != 3:
            return (None, None, None)

        try:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return (None, None, None)

    def __del__(self) -> None:
        """デストラクタ。

        プロセスが残っている場合は終了する。
        """
        if self._process and self._process.returncode is None:
            logger.warning("Process still running in __del__, terminating")
            self._process.terminate()
