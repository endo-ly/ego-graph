"""Webhook 送信 adapter。

CloudEvents-inspired JSON (Generic) と Discord Embed 形式 (Discord) の
2 種類の adapter を提供する。Platform 固有の拡張は adapter を追加する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from pipelines.domain.notification import NotificationEvent

DEFAULT_TIMEOUT_SECONDS = 5.0


def _format_time_iso8601_utc(event: NotificationEvent) -> str:
    """ISO 8601 UTC 文字列 ('Z' サフィックス) へ整形する。"""
    return event.time.isoformat().replace("+00:00", "Z")


class WebhookAdapter(ABC):
    """Webhook 送信の抽象基底クラス。"""

    @abstractmethod
    def send(self, url: str, event: NotificationEvent) -> None:
        """HTTP 送信する。HTTP 4xx/5xx 時は例外を送出すること。"""

    @staticmethod
    def _post_json(url: str, payload: dict) -> None:
        response = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()


class GenericAdapter(WebhookAdapter):
    """CloudEvents-inspired JSON をそのまま POST する汎用 adapter。"""

    def send(self, url: str, event: NotificationEvent) -> None:
        payload = {
            "source": event.source,
            "type": event.type,
            "time": _format_time_iso8601_utc(event),
            "data": {
                "workflow_id": event.data.workflow_id,
                "run_id": event.data.run_id,
                "error_message": event.data.error_message,
                "custom_message": event.data.custom_message,
            },
        }
        self._post_json(url, payload)


class DiscordAdapter(WebhookAdapter):
    """Discord Webhook 用 adapter。Embed 形式に変換して送信する。"""

    _RED_COLOR = 16711680
    _USERNAME = "EgoGraph Pipelines"

    def send(self, url: str, event: NotificationEvent) -> None:
        payload = {
            "username": self._USERNAME,
            "embeds": [
                {
                    "title": "Pipeline Failed",
                    "description": event.data.workflow_id,
                    "color": self._RED_COLOR,
                    "fields": [
                        {
                            "name": "Error",
                            "value": event.data.error_message or "(none)",
                        },
                        {
                            "name": "Action",
                            "value": event.data.custom_message or "(none)",
                        },
                        {"name": "Run ID", "value": event.data.run_id},
                    ],
                    "timestamp": _format_time_iso8601_utc(event),
                    "footer": {"text": event.source},
                }
            ],
        }
        self._post_json(url, payload)
