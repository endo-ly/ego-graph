"""tmux モジュールの単体テスト。

tmux セッションの列挙、パース機能のテストを行います。
"""

import re
import subprocess
from unittest.mock import Mock, patch

import pytest

from gateway.infrastructure.tmux import (
    _parse_tmux_timestamp,
    get_active_pane_metadata,
    list_sessions,
    session_exists,
)


class TestParseTmuxTimestamp:
    """tmux タイムスタンプパース関数のテスト。

    tmux から返される様々なタイムスタンプ形式のパースを検証します。
    """

    def test_iso_format_without_microseconds(self) -> None:
        """ISO 8601 形式（マイクロ秒なし）のパースを検証します。"""
        # Arrange: 正常な ISO 形式のタイムスタンプ
        timestamp_str = "2025-02-08T12:34:56"

        # Act: タイムスタンプをパース
        result = _parse_tmux_timestamp(timestamp_str)

        # Assert: 正常にパースされていること
        assert result.year == 2025
        assert result.month == 2
        assert result.day == 8
        assert result.hour == 12
        assert result.minute == 34
        assert result.second == 56

    def test_iso_format_with_microseconds(self) -> None:
        """ISO 8601 形式（マイクロ秒あり）のパースを検証します。"""
        # Arrange: マイクロ秒を含む ISO 形式のタイムスタンプ
        timestamp_str = "2025-02-08T12:34:56.123456"

        # Act: タイムスタンプをパース
        result = _parse_tmux_timestamp(timestamp_str)

        # Assert: 正常にパースされていること
        assert result.year == 2025
        assert result.month == 2
        assert result.day == 8
        assert result.hour == 12
        assert result.minute == 34
        assert result.second == 56
        assert result.microsecond == 123456

    def test_space_separator_format(self) -> None:
        """スペース区切り形式のパースを検証します。"""
        # Arrange: スペース区切りのタイムスタンプ
        timestamp_str = "2025-02-08 12:34:56"

        # Act: タイムスタンプをパース
        result = _parse_tmux_timestamp(timestamp_str)

        # Assert: 正常にパースされていること
        assert result.year == 2025
        assert result.month == 2
        assert result.day == 8

    def test_unix_epoch_seconds_format(self) -> None:
        """UNIX epoch 秒形式のパースを検証します。"""
        # Arrange: tmux が返す epoch 秒形式
        timestamp_str = "1770648271"

        # Act
        result = _parse_tmux_timestamp(timestamp_str)

        # Assert
        assert result.year >= 2025

    def test_invalid_format_raises_error(self) -> None:
        """無効な形式の場合に ValueError が発生することを検証します。"""
        # Arrange: 無効な形式のタイムスタンプ
        timestamp_str = "invalid-timestamp"

        # Act & Assert: ValueError が発生すること
        with pytest.raises(ValueError, match="Unsupported timestamp format"):
            _parse_tmux_timestamp(timestamp_str)


class TestListSessions:
    """list_sessions 関数のテスト。

    tmux セッション一覧取得の各種シナリオを検証します。
    """

    def test_returns_empty_list_when_no_sessions_exist(self) -> None:
        """セッションが存在しない場合に空リストを返すことを検証します。"""
        # Arrange: tmux コマンドが終了ステータス 1 で空の出力を返す
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 1
            result.stdout = ""
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 空リストが返されること
            assert sessions == []

    def test_filters_sessions_by_pattern(self) -> None:
        """正規表現パターンによるフィルタリングを検証します。"""
        # Arrange: 複数のセッションが存在するが、パターンに一致するもののみ返す
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "agent-0001\t2025-02-08T12:00:00\t2025-02-08T10:00:00\n"
                "other-session\t2025-02-08T12:00:00\t2025-02-08T10:00:00\n"
                "agent-0002\t2025-02-08T11:00:00\t2025-02-08T09:00:00"
            )
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: agent-* パターンに一致するセッションのみが返されること
            assert len(sessions) == 2
            assert sessions[0].name == "agent-0001"
            assert sessions[1].name == "agent-0002"

    def test_rejects_suffixed_agent_session_name(self) -> None:
        """接尾辞付きセッション名が除外されることを検証します。"""
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = "agent-0001-8\t2025-02-08T12:00:00\t2025-02-08T10:00:00"
            mock_run.return_value = result

            sessions = list_sessions()

            assert sessions == []

    def test_parses_session_output_correctly(self) -> None:
        """tmux 出力のパースを検証します。"""
        # Arrange: 正常な tmux 出力
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = "agent-0001\t2025-02-08T12:34:56\t2025-02-08T10:00:00"
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: セッション情報が正しくパースされていること
            assert len(sessions) == 1
            session = sessions[0]
            assert session.name == "agent-0001"
            assert session.last_activity.year == 2025
            assert session.last_activity.month == 2
            assert session.last_activity.day == 8
            assert session.last_activity.hour == 12
            assert session.last_activity.minute == 34
            assert session.created_at.hour == 10

    def test_parses_unix_epoch_timestamps(self) -> None:
        """tmux の UNIX epoch 秒形式の出力をパースできることを検証します。"""
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = "agent-0001\t1770648271\t1770648000"
            mock_run.return_value = result

            sessions = list_sessions()

            assert len(sessions) == 1
            assert sessions[0].name == "agent-0001"

    def test_handles_missing_sessions_gracefully(self) -> None:
        """tmux がインストールされていない場合の処理を検証します。"""
        # Arrange: tmux コマンドが FileNotFoundError を発生させる
        with patch("subprocess.run", side_effect=FileNotFoundError):
            # Act & Assert: OSError が発生すること
            with pytest.raises(OSError, match="tmux is not installed"):
                list_sessions()

    def test_handles_subprocess_error(self) -> None:
        """tmux コマンドが予期せぬエラーで失敗した場合の処理を検証します。"""
        # Arrange: tmux コマンドが終了ステータス 1 でエラー出力を出す
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 1
            result.stdout = ""  # 空出力だが、何らかのエラーメッセージがあると仮定
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 空リストが返されること（エラーはログに出力される）
            assert sessions == []

    def test_uses_custom_pattern_when_provided(self) -> None:
        """カスタムパターンの使用を検証します。"""
        # Arrange: カスタムパターン（test-* のみ）
        custom_pattern = r"^test-[0-9]+$"
        pattern = re.compile(custom_pattern)

        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "test-1\t2025-02-08T12:00:00\t2025-02-08T10:00:00\n"
                "agent-0001\t2025-02-08T12:00:00\t2025-02-08T10:00:00"
            )
            mock_run.return_value = result

            # Act: カスタムパターンでセッション一覧を取得
            sessions = list_sessions(pattern=pattern)

            # Assert: test-* パターンに一致するセッションのみが返されること
            assert len(sessions) == 1
            assert sessions[0].name == "test-1"


class TestSessionExists:
    """session_exists 関数のテスト。"""

    def test_returns_true_when_session_exists(self) -> None:
        """セッションが存在する場合に True を返すことを検証します。"""
        # Arrange: subprocess.run が成功する（終了ステータス 0）
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            mock_run.return_value = result

            # Act: セッションの存在確認
            exists = session_exists("agent-0001")

            # Assert: True が返されること
            assert exists is True
            # Assert: 正しいコマンドが呼ばれたこと
            mock_run.assert_called_once_with(
                ["tmux", "has-session", "-t", "=agent-0001"],
                capture_output=True,
                check=True,
                timeout=5,
            )

    def test_returns_false_when_session_not_exists(self) -> None:
        """セッションが存在しない場合に False を返すことを検証します。"""
        # Arrange: subprocess.run が CalledProcessError を発生させる
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["tmux", "has-session", "-t", "agent-9999"]
            )

            # Act: 存在しないセッションの確認
            exists = session_exists("agent-9999")

            # Assert: False が返されること
            assert exists is False

    def test_returns_false_when_tmux_not_found(self) -> None:
        """tmux がインストールされていない場合に False を返すことを検証します。"""
        # Arrange: subprocess.run が FileNotFoundError を発生させる
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("tmux not found")

            # Act: セッションの存在確認
            exists = session_exists("agent-0001")

            # Assert: False が返されること
            assert exists is False

    def test_returns_false_when_timeout(self) -> None:
        """tmux コマンドがタイムアウトした場合に False を返すことを検証します。"""
        # Arrange: subprocess.run が TimeoutExpired を発生させる
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["tmux", "has-session", "-t", "=agent-0001"], timeout=5
            )

            # Act: セッションの存在確認
            exists = session_exists("agent-0001")

            # Assert: False が返されること
            assert exists is False


class TestGetActivePaneMetadata:
    """get_active_pane_metadata 関数のテスト。"""

    def test_returns_active_pane_title_and_path(self) -> None:
        """複数 pane があっても active pane の情報を返すことを検証します。"""
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.stdout = (
                "0\tother title\t/tmp/other\n"
                "1\tClaude Code\t/root/workspace/ego-graph\n"
            )
            mock_run.return_value = result

            title, current_path = get_active_pane_metadata("agent-0001")

            assert title == "Claude Code"
            assert current_path == "/root/workspace/ego-graph"

    def test_preserves_blank_title_for_active_pane(self) -> None:
        """active pane のタイトルが空でも current_path が保持されることを検証します。"""
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.stdout = "1\t\t/root/workspace/ego-graph\n"
            mock_run.return_value = result

            title, current_path = get_active_pane_metadata("agent-0001")

            assert title is None
            assert current_path == "/root/workspace/ego-graph"

    def test_falls_back_to_first_pane_when_active_flag_missing(self) -> None:
        """active pane が見つからない場合は先頭 pane の情報へフォールバックすることを検証します。"""
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.stdout = (
                "0\tClaude Code\t/root/workspace/ego-graph\n"
                "0\tOther\t/tmp/other\n"
            )
            mock_run.return_value = result

            title, current_path = get_active_pane_metadata("agent-0001")

            assert title == "Claude Code"
            assert current_path == "/root/workspace/ego-graph"

    def test_returns_none_pair_on_tmux_failure(self) -> None:
        """tmux 実行に失敗した場合は None ペアを返すことを検証します。"""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tmux", timeout=5)):
            assert get_active_pane_metadata("agent-0001") == (None, None)


class TestListSessionsTimeoutHandling:
    """list_sessions 関数のタイムアウト処理に関するテスト。

    tmux コマンドが応答しない場合のタイムアウト処理を検証します。
    """

    def test_handles_timeout_gracefully(self) -> None:
        """tmux コマンドがタイムアウトした場合に OSError を発生させることを検証します。"""
        # Arrange: subprocess.run が TimeoutExpired を発生させる
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["tmux", "list-sessions"], timeout=5
            )

            # Act & Assert: OSError が発生すること
            with pytest.raises(OSError, match="tmux list-sessions timed out"):
                list_sessions()

    def test_propagates_timeout_with_correct_timeout_value(self) -> None:
        """指定されたタイムアウト値で subprocess.run が呼ばれることを検証します。"""
        # Arrange: subprocess.run をモック化
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = ""
            mock_run.return_value = result

            # Act: セッション一覧を取得
            list_sessions()

            # Assert: タイムアウト値が正しく設定されていること
            call_args = mock_run.call_args
            assert call_args.kwargs["timeout"] == 5


class TestListSessionsEdgeCases:
    """list_sessions 関数のエッジケースに関するテスト。

    入力データの境界条件や異常形式に対する処理を検証します。
    """

    def test_handles_empty_lines_in_output(self) -> None:
        """出力に空行が含まれる場合の処理を検証します。"""
        # Arrange: 空行を含む tmux 出力
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "agent-0001\t2025-02-08T12:00:00\t2025-02-08T10:00:00\n"
                "\n"
                "agent-0002\t2025-02-08T11:00:00\t2025-02-08T09:00:00\n"
                "\n"
            )
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 空行がスキップされ、有効なセッションのみが返されること
            assert len(sessions) == 2
            assert sessions[0].name == "agent-0001"
            assert sessions[1].name == "agent-0002"

    def test_handles_output_with_extra_tabs(self) -> None:
        """出力に余分なタブが含まれる場合の処理を検証します。"""
        # Arrange: タブの数が不正な形式（無効な出力とみなされる）
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "agent-0001\t2025-02-08T12:00:00\t2025-02-08T10:00:00\n"
                "agent-0002\t2025-02-08T11:00:00\t2025-02-08T09:00:00\textra"
            )
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 不正な形式の行がスキップされること
            assert len(sessions) == 1
            assert sessions[0].name == "agent-0001"

    def test_handles_output_with_fewer_tabs(self) -> None:
        """出力のタブが不足している場合の処理を検証します。"""
        # Arrange: タブの数が不足する形式
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "agent-0001\t2025-02-08T12:00:00\t2025-02-08T10:00:00\n"
                "agent-0002\t2025-02-08T11:00:00"
            )
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 不正な形式の行がスキップされること
            assert len(sessions) == 1
            assert sessions[0].name == "agent-0001"

    def test_handles_all_invalid_output(self) -> None:
        """全ての出力行が無効な形式の場合の処理を検証します。"""
        # Arrange: 全ての行が不正な形式
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = "invalid-line-1\ninvalid-line-2\ninvalid-line-3"
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 空リストが返されること
            assert sessions == []

    def test_handles_trailing_newline(self) -> None:
        """出力の末尾に改行がある場合の処理を検証します。"""
        # Arrange: 末尾に改行がある出力
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = "agent-0001\t2025-02-08T12:00:00\t2025-02-08T10:00:00\n"
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 正常にパースされていること
            assert len(sessions) == 1
            assert sessions[0].name == "agent-0001"

    def test_returns_empty_list_for_no_matching_sessions(self) -> None:
        """パターンに一致するセッションが存在しない場合の処理を検証します。"""
        # Arrange: セッションは存在するがパターンに一致しない
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = "other-session\t2025-02-08T12:00:00\t2025-02-08T10:00:00"
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 空リストが返されること
            assert sessions == []


class TestListSessionsTimestampFallback:
    """list_sessions 関数のタイムスタンプパース失敗時のフォールバック処理に関するテスト。

    タイムスタンプのパースに失敗した場合の挙動を検証します。
    """

    def test_fallback_to_created_when_activity_parse_fails(self) -> None:
        """最終アクティビティのパースに失敗した場合に作成日時をフォールバックとして使用することを検証します。"""
        # Arrange: 最終アクティビティが無効な形式で作成日時が有効な形式
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = "agent-0001\tinvalid-timestamp\t2025-02-08T10:00:00"
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 作成日時が最終アクティビティとして使用されること
            assert len(sessions) == 1
            assert sessions[0].name == "agent-0001"
            assert sessions[0].last_activity.hour == 10
            assert sessions[0].created_at.hour == 10

    def test_uses_current_time_when_both_timestamps_fail(self) -> None:
        """両方のタイムスタンプのパースに失敗した場合に現在時刻へフォールバックすることを検証します。"""
        # Arrange: 両方のタイムスタンプが無効な形式
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "agent-0001\tinvalid-activity\t2025-02-08T10:00:00\n"
                "agent-0002\tinvalid-activity\tinvalid-created"
            )
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: パース不能なセッションも現在時刻フォールバックで返されること
            assert len(sessions) == 2
            assert sessions[0].name == "agent-0001"
            assert sessions[1].name == "agent-0002"
            assert sessions[1].last_activity.tzinfo is not None
            assert sessions[1].created_at.tzinfo is not None

    def test_handles_mixed_timestamp_formats(self) -> None:
        """異なるタイムスタンプ形式が混在する場合の処理を検証します。"""
        # Arrange: ISO 形式と UNIX epoch 形式が混在
        with patch("subprocess.run") as mock_run:
            result = Mock()
            result.returncode = 0
            result.stdout = (
                "agent-0001\t1770648271\t1770648000\n"
                "agent-0002\t2025-02-08T12:00:00\t2025-02-08T10:00:00"
            )
            mock_run.return_value = result

            # Act: セッション一覧を取得
            sessions = list_sessions()

            # Assert: 両方の形式が正しくパースされていること
            assert len(sessions) == 2
            # UNIX epoch 形式のセッション
            assert sessions[0].name == "agent-0001"
            assert sessions[0].last_activity.year >= 2025
            # ISO 形式のセッション
            assert sessions[1].name == "agent-0002"
            assert sessions[1].last_activity.hour == 12


class TestListSessionsErrorHandling:
    """list_sessions 関数のエラーハンドリングに関するテスト。

    予期しないエラー状態に対する処理を検証します。
    """

    def test_propagates_non_empty_stdout_errors(self) -> None:
        """終了ステータス 1 で標準出力がある場合にエラーを伝播することを検証します。"""
        # Arrange: tmux コマンドが終了ステータス 1 で標準出力を持つ
        with patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(
                returncode=1, cmd=["tmux", "list-sessions"]
            )
            error.stdout = "some-error-output"
            mock_run.side_effect = error

            # Act & Assert: CalledProcessError が伝播すること
            with pytest.raises(subprocess.CalledProcessError):
                list_sessions()

    def test_handles_generic_exception(self) -> None:
        """予期しない例外が発生した場合の処理を検証します。"""
        # Arrange: subprocess.run が予期しない例外を発生させる
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("Unexpected error")

            # Act & Assert: 例外が伝播すること
            with pytest.raises(RuntimeError, match="Unexpected error"):
                list_sessions()
