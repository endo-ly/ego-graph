"""Pipeline 失敗通知サービス。

Webhook 送信は adapter 層に委譲し、本サービスでは ``custom_message`` の
組み立てと送信失敗時の握りつぶしを担当する。
"""

from __future__ import annotations

import logging
from dataclasses import replace

from pipelines.domain.errors import AuthenticationError
from pipelines.domain.notification import NotificationEvent
from pipelines.infrastructure.notification.adapters import (
    DiscordAdapter,
    GenericAdapter,
    WebhookAdapter,
)

logger = logging.getLogger(__name__)


def _custom_message_for(exc: Exception | None) -> str | None:
    """例外型からユーザー/エージェント向けメッセージを組み立てる。

    新たな例外型に対応するときはここに ``isinstance`` 分岐を追加するだけで
    済む（Open/Closed）。
    """
    if exc is None:
        return None
    if isinstance(exc, AuthenticationError):
        return (
            "認証でエラーが発生しました。"
            "再認証スクリプトを実行してください: "
            "uv run python scripts/spotify_auth.py"
        )
    return None


class NotificationService:
    """Pipeline 失敗時の通知サービス。"""

    def __init__(
        self,
        *,
        webhook_url: str | None,
        webhook_type: str = "generic",
    ) -> None:
        """``webhook_url`` が ``None`` のとき通知は無効化される。"""
        self._webhook_url = webhook_url
        self._adapter: WebhookAdapter = self._create_adapter(webhook_type)

    @property
    def enabled(self) -> bool:
        """通知が有効（webhook URL 設定済み）か。"""
        return self._webhook_url is not None

    def notify(self, event: NotificationEvent, exc: Exception | None = None) -> None:
        """イベントを Webhook 送信する。送信失敗は Pipeline を阻害しない。"""
        if not self._webhook_url:
            return
        enriched = self._enrich_with_custom_message(event, exc)
        try:
            self._adapter.send(self._webhook_url, enriched)
        except Exception:
            logger.exception(
                "Failed to send webhook notification: type=%s, run_id=%s",
                enriched.type,
                enriched.data.run_id,
            )

    @staticmethod
    def _create_adapter(webhook_type: str) -> WebhookAdapter:
        if webhook_type == "discord":
            return DiscordAdapter()
        if webhook_type == "generic":
            return GenericAdapter()
        raise ValueError(
            f"unsupported webhook_type: {webhook_type!r} "
            "(expected 'generic' or 'discord')"
        )

    @staticmethod
    def _enrich_with_custom_message(
        event: NotificationEvent,
        exc: Exception | None,
    ) -> NotificationEvent:
        """``event.data.custom_message`` 未設定時に ``exc`` から補完する。"""
        if event.data.custom_message is not None:
            return event
        custom = _custom_message_for(exc)
        if custom is None:
            return event
        return replace(event, data=replace(event.data, custom_message=custom))
