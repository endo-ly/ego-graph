"""Utility helpers for pipelines source modules."""

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from functools import wraps

logger = logging.getLogger(__name__)


def log_execution_time[T: Callable](func: T) -> T:
    """関数の実行時間をログ出力する。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = datetime.now(timezone.utc)
        logger.info("Starting %s", func.__name__)
        try:
            result = func(*args, **kwargs)
        except Exception:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.exception("Failed %s after %.2fs", func.__name__, elapsed)
            raise
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info("Completed %s in %.2fs", func.__name__, elapsed)
        return result

    return wrapper


def iso8601_to_unix_ms(iso_timestamp) -> int:
    """ISO8601 文字列または timezone-aware datetime を Unix ms に変換する。"""
    try:
        if isinstance(iso_timestamp, datetime):
            if iso_timestamp.tzinfo is None:
                raise ValueError(
                    "Naive datetime (timezone-unaware) is not supported. "
                    "Please provide a timezone-aware datetime object."
                )
            return int(iso_timestamp.timestamp() * 1000)

        normalized = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"Failed to parse timestamp '{iso_timestamp}': {exc}") from exc
