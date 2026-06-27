"""ログ出力時のインフラ情報マスキングユーティリティ。

S3 バケット名や R2 エンドポイントURLなど、
外部に漏洩すべきでないインフラ情報をログから sanitizing する。
"""

import logging
import re
import traceback

# s3://<bucket-name>/<path> → ***/<path>
_S3_PATTERN = re.compile(r"s3://[^/]+")
_S3_REPLACEMENT = r"***"

# https://<subdomain>.r2.cloudflarestorage.com → ***
_R2_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.r2\.cloudflarestorage\.com")
_R2_REPLACEMENT = r"***"


def sanitize_infra_message(message: str) -> str:
    """メッセージ内のインフラ情報をマスクする。

    Args:
        message: サニタイズ対象の文字列。

    Returns:
        インフラ情報がマスクされた文字列。
    """
    result = _S3_PATTERN.sub(_S3_REPLACEMENT, message)
    result = _R2_PATTERN.sub(_R2_REPLACEMENT, result)
    return result


def sanitize_exception(exc: Exception) -> str:
    """例外メッセージ内のインフラ情報をマスクする。

    Args:
        exc: サニタイズ対象の例外。

    Returns:
        インフラ情報がマスクされた例外メッセージ文字列。
    """
    return sanitize_infra_message(str(exc))


class InfraSanitizingFilter(logging.Filter):
    """ログレコードからインフラ情報を自動的にマスクする logging.Filter。

    - record.msg を args 展開済みの完全メッセージにしてからサニタイズする
    - record.args をクリアし、再フォーマットを防止する
    - record.exc_info がある場合、トレースバックをフォーマットしてサニタイズする
    - record.exc_text（トレースバック）が存在すればサニタイズする
    - すべてのレコードを通過させる（ドロップしない）
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """ログレコードをサニタイズして通過させる。

        msg と args を先にフォーマット展開し、完全なメッセージをサニタイズする。
        これにより args に含まれる秘密もマスク対象になり、args クリア後も
        プレースホルダが未展開で残らない。フォーマット失敗時は生 msg を扱う。

        Args:
            record: フィルタ対象のログレコード。

        Returns:
            常に True（レコードをドロップしない）。
        """
        if isinstance(record.msg, str):
            try:
                message = record.getMessage()
            except (TypeError, ValueError):
                message = record.msg
            record.msg = sanitize_infra_message(message)

        record.args = None

        if record.exc_info and not record.exc_text:
            record.exc_text = "".join(
                traceback.format_exception(*record.exc_info)
            )

        if record.exc_text:
            record.exc_text = sanitize_infra_message(record.exc_text)

        return True
