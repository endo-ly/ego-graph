"""通知系 (adapters / service) のテスト。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import requests
from pipelines.domain.errors import AuthenticationError
from pipelines.domain.notification import NotificationData, NotificationEvent
from pipelines.infrastructure.notification.adapters import (
    DEFAULT_TIMEOUT_SECONDS,
    DiscordAdapter,
    GenericAdapter,
    WebhookAdapter,
)
from pipelines.infrastructure.notification.service import (
    NotificationService,
    _custom_message_for,
)


def _make_event(
    *,
    custom_message: str | None = None,
    error_message: str | None = "boom",
) -> NotificationEvent:
    return NotificationEvent(
        source="urn:egograph:pipelines",
        type="egograph.pipelines.workflow_failed",
        time=datetime(2026, 6, 5, 14, 0, 2, tzinfo=UTC),
        data=NotificationData(
            workflow_id="spotify_ingest_workflow",
            run_id="722e2f38-def8-4bba-9283-bfe07459935c",
            error_message=error_message,
            custom_message=custom_message,
        ),
    )


# ===== WebhookAdapter 抽象 =====


def test_webhook_adapter_is_abstract():
    """WebhookAdapter は直接インスタンス化できない。"""
    with pytest.raises(TypeError):
        WebhookAdapter()


# ===== GenericAdapter =====


def test_generic_adapter_posts_cloudevents_inspired_json():
    """GenericAdapter は CloudEvents-inspired JSON を POST する。"""
    # Arrange
    adapter = GenericAdapter()
    event = _make_event(custom_message="再認証してください")

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        adapter.send("https://example.com/webhook", event)

    # Assert
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args == ("https://example.com/webhook",)
    assert kwargs["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert kwargs["json"] == {
        "source": "urn:egograph:pipelines",
        "type": "egograph.pipelines.workflow_failed",
        "time": "2026-06-05T14:00:02Z",
        "data": {
            "workflow_id": "spotify_ingest_workflow",
            "run_id": "722e2f38-def8-4bba-9283-bfe07459935c",
            "error_message": "boom",
            "custom_message": "再認証してください",
        },
    }


def test_generic_adapter_raises_on_http_error():
    """HTTP 4xx/5xx で HTTPError を送出する。"""
    # Arrange
    adapter = GenericAdapter()
    event = _make_event()

    # Act & Assert
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_response = mock_post.return_value
        mock_response.raise_for_status.side_effect = requests.HTTPError("500")
        with pytest.raises(requests.HTTPError):
            adapter.send("https://example.com/webhook", event)


# ===== DiscordAdapter =====


def test_discord_adapter_posts_embed_payload():
    """DiscordAdapter は Embed 形式に変換して POST する。"""
    # Arrange
    adapter = DiscordAdapter()
    event = _make_event(custom_message="再認証スクリプト実行")

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 204
        adapter.send("https://discord.com/api/webhooks/abc", event)

    # Assert
    args, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert kwargs["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert payload["username"] == "EgoGraph Pipelines"
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["title"] == "Pipeline Failed"
    assert embed["description"] == "spotify_ingest_workflow"
    assert embed["color"] == 16711680
    assert embed["timestamp"] == "2026-06-05T14:00:02Z"
    assert embed["footer"]["text"] == "urn:egograph:pipelines"
    field_names = [f["name"] for f in embed["fields"]]
    assert "Error" in field_names
    assert "Action" in field_names
    assert "Run ID" in field_names
    # payloads are JSON-serializable
    json.dumps(payload)


def test_discord_adapter_uses_none_fallback_for_empty_messages():
    """error_message / custom_message が None なら '(none)' に置換される。"""
    # Arrange
    adapter = DiscordAdapter()
    event = _make_event(error_message=None, custom_message=None)

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 204
        adapter.send("https://discord.com/api/webhooks/abc", event)

    # Assert
    payload = mock_post.call_args.kwargs["json"]
    fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
    assert fields["Error"] == "(none)"
    assert fields["Action"] == "(none)"


# ===== _custom_message_for =====


def test_custom_message_for_authentication_error_returns_spotify_hint():
    """AuthenticationError → Spotify 再認証手順。"""
    # Arrange
    exc = AuthenticationError("Spotify refresh token revoked")

    # Act
    msg = _custom_message_for(exc)

    # Assert
    assert msg is not None
    assert "認証" in msg
    assert "spotify_auth.py" in msg


def test_custom_message_for_other_exception_returns_none():
    """未知の例外型は custom_message を出さない。"""
    assert _custom_message_for(RuntimeError("boom")) is None
    assert _custom_message_for(ValueError("nope")) is None


def test_custom_message_for_none_returns_none():
    """exc=None なら custom_message を出さない。"""
    assert _custom_message_for(None) is None


# ===== NotificationService =====


def test_service_disabled_when_webhook_url_is_none():
    """webhook_url 未設定時は何もせず正常終了する。"""
    # Arrange
    service = NotificationService(webhook_url=None)
    event = _make_event()

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        service.notify(event)

    # Assert
    mock_post.assert_not_called()
    assert service.enabled is False


def test_service_sends_event_when_webhook_url_is_set():
    """webhook_url 設定時は adapter.send が呼ばれる。"""
    # Arrange
    service = NotificationService(webhook_url="https://example.com/hook")
    event = _make_event()

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        service.notify(event)

    # Assert
    mock_post.assert_called_once()


def test_service_enriches_custom_message_for_authentication_error():
    """exc=AuthenticationError 渡下で custom_message が補完される。"""
    # Arrange
    service = NotificationService(webhook_url="https://example.com/hook")
    event = _make_event(custom_message=None)
    exc = AuthenticationError("revoked")

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        service.notify(event, exc=exc)

    # Assert
    payload = mock_post.call_args.kwargs["json"]
    assert payload["data"]["custom_message"] is not None
    assert "spotify_auth.py" in payload["data"]["custom_message"]


def test_service_does_not_overwrite_existing_custom_message():
    """event.data.custom_message 設定済みなら上書きしない。"""
    # Arrange
    service = NotificationService(webhook_url="https://example.com/hook")
    event = _make_event(custom_message="既設の指示")
    exc = AuthenticationError("revoked")

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        service.notify(event, exc=exc)

    # Assert
    payload = mock_post.call_args.kwargs["json"]
    assert payload["data"]["custom_message"] == "既設の指示"


def test_service_does_not_enrich_when_exc_is_none():
    """exc=None なら custom_message は補完しない。"""
    # Arrange
    service = NotificationService(webhook_url="https://example.com/hook")
    event = _make_event(custom_message=None)

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.return_value.status_code = 200
        service.notify(event, exc=None)

    # Assert
    payload = mock_post.call_args.kwargs["json"]
    assert payload["data"]["custom_message"] is None


def test_service_swallows_adapter_failure_with_log(caplog):
    """adapter 送信失敗時に Pipeline を阻害せず logger.exception だけ出す。"""
    # Arrange
    service = NotificationService(webhook_url="https://example.com/hook")
    event = _make_event()

    # Act
    with patch(
        "pipelines.infrastructure.notification.adapters.requests.post"
    ) as mock_post:
        mock_post.side_effect = requests.ConnectionError("connection refused")
        with caplog.at_level(
            logging.ERROR, logger="pipelines.infrastructure.notification.service"
        ):
            service.notify(event)

    # Assert: 例外が伝播しない
    mock_post.assert_called_once()
    assert "Failed to send webhook notification" in caplog.text
    assert event.data.run_id in caplog.text


def test_service_rejects_unknown_webhook_type():
    """未知の webhook_type は ValueError。"""
    with pytest.raises(ValueError, match="unsupported webhook_type"):
        NotificationService(webhook_url="https://x", webhook_type="slack")
