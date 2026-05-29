"""インフラ情報サニタイザーのテスト。"""

import io
import logging

from backend.infrastructure.logging.sanitizers import (
    InfraSanitizingFilter,
    sanitize_exception,
    sanitize_infra_message,
)
from backend.main import create_app


class TestSanitizeInfraMessage:
    """sanitize_infra_message のテスト。"""

    def test_sanitize_masks_s3_url(self):
        """s3:// URL のバケット名をマスクする。"""
        # Arrange
        message = "Connecting to s3://my-secret-bucket/data/file.parquet"

        # Act
        result = sanitize_infra_message(message)

        # Assert
        assert "my-secret-bucket" not in result
        assert "s3://" not in result
        assert "***/data/file.parquet" in result

    def test_sanitize_masks_r2_endpoint_url(self):
        """R2 エンドポイント URL のホスト名をマスクする。"""
        # Arrange
        message = "Failed to connect to https://abc123.r2.cloudflarestorage.com/v1/data"

        # Act
        result = sanitize_infra_message(message)

        # Assert
        assert "abc123" not in result
        assert "r2.cloudflarestorage.com" not in result
        assert "***" in result

    def test_sanitize_preserves_non_infra_text(self):
        """インフラ情報を含まないテキストは変更されない。"""
        # Arrange
        message = "Hello, this is a normal log message"

        # Act
        result = sanitize_infra_message(message)

        # Assert
        assert result == message

    def test_sanitize_masks_multiple_occurrences(self):
        """複数の s3:// URL をすべてマスクする。"""
        # Arrange
        message = "Reading s3://bucket-a/file1.parquet and s3://bucket-b/file2.parquet"

        # Act
        result = sanitize_infra_message(message)

        # Assert
        assert "bucket-a" not in result
        assert "bucket-b" not in result
        assert "s3://" not in result
        assert result.count("***/") == 2

    def test_sanitize_empty_string(self):
        """空文字列はそのまま通過する。"""
        # Arrange
        message = ""

        # Act
        result = sanitize_infra_message(message)

        # Assert
        assert result == ""


class TestSanitizeException:
    """sanitize_exception のテスト。"""

    def test_sanitize_exception_applies_message_sanitization(self):
        """例外メッセージ内のインフラ情報をマスクする。"""
        # Arrange
        exc = RuntimeError("Failed to read s3://prod-bucket/events/spotify.parquet")

        # Act
        result = sanitize_exception(exc)

        # Assert
        assert "prod-bucket" not in result
        assert "s3://" not in result
        assert "***" in result


class TestInfraSanitizingFilter:
    """InfraSanitizingFilter のテスト。"""

    def test_infra_sanitizing_filter_masks_log_message(self):
        """LogRecord のメッセージ内 s3:// URL をマスクする。"""
        # Arrange
        filt = InfraSanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Accessing s3://my-bucket/data.parquet",
            args=None,
            exc_info=None,
        )

        # Act
        result = filt.filter(record)

        # Assert
        assert result is True
        assert "my-bucket" not in record.msg
        assert "s3://" not in record.msg
        assert "***" in record.msg

    def test_infra_sanitizing_filter_masks_traceback(self):
        """LogRecord のトレースバック内 R2 URL をマスクする。"""
        # Arrange
        filt = InfraSanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error occurred",
            args=None,
            exc_info=None,
        )
        record.exc_text = (
            "Traceback:\n  ConnectionError: https://xyz.r2.cloudflarestorage.com failed"
        )

        # Act
        filt.filter(record)

        # Assert
        assert "xyz" not in record.exc_text
        assert "r2.cloudflarestorage.com" not in record.exc_text
        assert "***" in record.exc_text

    def test_infra_sanitizing_filter_preserves_clean_messages(self):
        """インフラ情報を含まないメッセージはそのまま通過する。"""
        # Arrange
        filt = InfraSanitizingFilter()
        original_msg = "Application started successfully"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=original_msg,
            args=None,
            exc_info=None,
        )

        # Act
        result = filt.filter(record)

        # Assert
        assert result is True
        assert record.msg == original_msg

    def test_infra_sanitizing_filter_clears_args(self):
        """LogRecord の args をクリアし再フォーマットを防止する。"""
        # Arrange
        filt = InfraSanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Connecting to %s",
            args=("s3://secret-bucket/path",),
            exc_info=None,
        )

        # Act
        filt.filter(record)

        # Assert
        assert record.args is None


class TestFilterRegistration:
    """アプリケーション起動時のフィルター登録テスト。"""

    def test_log_filter_registered_on_app_startup(self, mock_backend_config):
        """create_app() 後にルートロガーへ InfraSanitizingFilter が登録される。"""
        # Arrange: フィルター登録前の状態を確認

        # Act: アプリケーションを生成
        create_app(config=mock_backend_config)

        # Assert: ルートロガーに InfraSanitizingFilter が存在する
        has_filter = any(
            isinstance(f, InfraSanitizingFilter) for f in logging.root.filters
        )
        assert has_filter

    def test_log_output_sanitized_via_filter(self):
        """フィルター経由で出力されたログから R2 URL が除外される。"""
        # Arrange: StringIO ハンドラーでログをキャプチャ
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(InfraSanitizingFilter())
        test_logger = logging.getLogger("test_sanitized_output")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)

        # Act: R2 URL を含むログを出力
        test_logger.info("Connecting to https://xyz.r2.cloudflarestorage.com/data")
        output = stream.getvalue()
        test_logger.removeHandler(handler)

        # Assert: 出力に R2 サブドメインが含まれない
        assert "xyz" not in output
        assert "r2.cloudflarestorage.com" not in output
        assert "***" in output
