"""機密 query parameter を access log から除外する。"""

from __future__ import annotations

import logging

OAUTH_CALLBACK_PATH = "/v1/sources/google-health/auth/callback"


class OAuthCallbackAccessLogFilter(logging.Filter):
    """OAuth callback の query string を Uvicorn access log で伏せる。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 3:
            return True
        request_target = record.args[2]
        if not isinstance(request_target, str):
            return True
        if not request_target.startswith(f"{OAUTH_CALLBACK_PATH}?"):
            return True
        args = list(record.args)
        args[2] = f"{OAUTH_CALLBACK_PATH}?[REDACTED]"
        record.args = tuple(args)
        return True


def install_access_log_filters() -> None:
    """Uvicorn access logger に OAuth callback redaction を設定する。"""
    logger = logging.getLogger("uvicorn.access")
    if not any(
        isinstance(item, OAuthCallbackAccessLogFilter) for item in logger.filters
    ):
        logger.addFilter(OAuthCallbackAccessLogFilter())
