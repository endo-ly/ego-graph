"""ドメインモデルの単体テスト。"""

import json

import pytest
from pydantic import ValidationError

from gateway.domain.models import (
    PushNotificationRequest,
    TerminalSession,
    TerminalSnapshotResponse,
    WebhookPayload,
    WSScrollMessage,
)

# ============================================================================
# TestTerminalSession - creates_with_defaults
# ============================================================================


class TestTerminalSession:
    """TerminalSessionモデルのテスト。"""

    def test_creates_with_defaults(self):
        """デフォルト値でセッションが作成されることを確認する。"""
        # Arrange
        session_id = "agent-0001"

        # Act
        session = TerminalSession(session_id=session_id)

        # Assert
        assert session.session_id == session_id
        assert session.activity is None
        assert session.created is None
        assert session.preview_available is False
        assert session.preview_lines == []

    def test_creates_with_all_fields(self):
        """全フィールドを指定してセッションが作成されることを確認する。"""
        # Arrange
        session_data = {
            "session_id": "agent-0001",
            "activity": "2025-02-10 10:30:00",
            "created": "2025-02-10 09:00:00",
            "preview_available": True,
            "preview_lines": ["$ uv run pytest", "2 passed"],
        }

        # Act
        session = TerminalSession(**session_data)

        # Assert
        assert session.session_id == "agent-0001"
        assert session.activity == "2025-02-10 10:30:00"
        assert session.created == "2025-02-10 09:00:00"
        assert session.preview_available is True
        assert session.preview_lines == ["$ uv run pytest", "2 passed"]

    def test_requires_session_id(self):
        """session_idが必須であることを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            TerminalSession()

        assert "session_id" in str(exc_info.value).lower()

    def test_serializes_to_json(self):
        """モデルがJSONにシリアライズされることを確認する。"""
        # Arrange
        session = TerminalSession(
            session_id="agent-0001",
            activity="2025-02-10 10:30:00",
            created="2025-02-10 09:00:00",
            preview_available=True,
            preview_lines=["$ uv run pytest", "2 passed"],
        )

        # Act
        json_str = session.model_dump_json()
        parsed = json.loads(json_str)

        # Assert
        assert parsed["session_id"] == "agent-0001"
        assert parsed["activity"] == "2025-02-10 10:30:00"
        assert parsed["created"] == "2025-02-10 09:00:00"
        assert parsed["preview_available"] is True
        assert parsed["preview_lines"] == ["$ uv run pytest", "2 passed"]

    def test_allows_preview_lines_longer_than_four(self):
        """preview_lines が 4 行を超えても保持されることを確認する。"""
        session = TerminalSession(
            session_id="agent-0001",
            preview_available=True,
            preview_lines=["1", "2", "3", "4", "5"],
        )

        assert session.preview_lines == ["1", "2", "3", "4", "5"]


class TestTerminalSnapshotResponse:
    """TerminalSnapshotResponse モデルのテスト。"""

    def test_serializes_to_json(self):
        """snapshot レスポンスが JSON にシリアライズされることを確認する。"""
        response = TerminalSnapshotResponse(
            session_id="agent-0001",
            content="line 1\nline 2",
        )

        parsed = json.loads(response.model_dump_json())

        assert parsed["session_id"] == "agent-0001"
        assert parsed["content"] == "line 1\nline 2"


class TestWSScrollMessage:
    """WSScrollMessage モデルのテスト。"""

    def test_accepts_scroll_lines_within_range(self):
        message = WSScrollMessage(lines=-6)

        assert message.type == "scroll"
        assert message.lines == -6

    def test_rejects_scroll_lines_out_of_range(self):
        with pytest.raises(ValidationError):
            WSScrollMessage(lines=21)


# ============================================================================
# TestPushNotificationRequest - validates_required_fields
# ============================================================================


class TestPushNotificationRequest:
    """PushNotificationRequestモデルのテスト。"""

    def test_validates_required_fields(self):
        """必須フィールドのバリデーションが動作することを確認する。"""
        # Arrange
        title = "Task Completed"
        body = "Your task has been completed successfully."

        # Act
        request = PushNotificationRequest(title=title, body=body)

        # Assert
        assert request.title == title
        assert request.body == body
        assert request.data is None

    def test_requires_title(self):
        """titleが必須であることを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            PushNotificationRequest(body="test body")

        assert "title" in str(exc_info.value).lower()

    def test_requires_body(self):
        """bodyが必須であることを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            PushNotificationRequest(title="test title")

        assert "body" in str(exc_info.value).lower()

    def test_title_min_length_validation(self):
        """titleの最小長バリデーションが動作することを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            PushNotificationRequest(title="", body="test body")

        assert "at least 1 character" in str(exc_info.value).lower()

    def test_title_max_length_validation(self):
        """titleの最大長バリデーションが動作することを確認する。"""
        # Arrange
        long_title = "a" * 101

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            PushNotificationRequest(title=long_title, body="test body")

        assert "at most 100 character" in str(exc_info.value).lower()

    def test_body_min_length_validation(self):
        """bodyの最小長バリデーションが動作することを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            PushNotificationRequest(title="test title", body="")

        assert "at least 1 character" in str(exc_info.value).lower()

    def test_body_max_length_validation(self):
        """bodyの最大長バリデーションが動作することを確認する。"""
        # Arrange
        long_body = "a" * 501

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            PushNotificationRequest(title="test title", body=long_body)

        assert "at most 500 character" in str(exc_info.value).lower()

    def test_accepts_optional_data(self):
        """オプションのdataフィールドが受け入れられることを確認する。"""
        # Arrange
        data = {"task_id": "123", "status": "completed"}

        # Act
        request = PushNotificationRequest(
            title="Task Completed", body="Your task has been completed.", data=data
        )

        # Assert
        assert request.data == data

    def test_data_defaults_to_none(self):
        """dataが指定されない場合にNoneになることを確認する。"""
        # Arrange & Act
        request = PushNotificationRequest(title="Test", body="Body")

        # Assert
        assert request.data is None


# ============================================================================
# TestWebhookPayload - serializes_to_json
# ============================================================================


class TestWebhookPayload:
    """WebhookPayloadモデルのテスト。"""

    def test_serializes_to_json(self):
        """モデルがJSONにシリアライズされることを確認する。"""
        # Arrange
        payload = WebhookPayload(
            type="task_completed",
            session_id="agent-0001",
            title="Task Completed",
            body="Your task has been completed successfully.",
        )

        # Act
        json_str = payload.model_dump_json()
        parsed = json.loads(json_str)

        # Assert
        assert parsed["type"] == "task_completed"
        assert parsed["session_id"] == "agent-0001"
        assert parsed["title"] == "Task Completed"
        assert parsed["body"] == "Your task has been completed successfully."

    def test_creates_with_all_fields(self):
        """全フィールドを指定してペイロードが作成されることを確認する。"""
        # Arrange
        payload_data = {
            "type": "task_completed",
            "session_id": "agent-0001",
            "title": "Task Completed",
            "body": "Your task has been completed successfully.",
        }

        # Act
        payload = WebhookPayload(**payload_data)

        # Assert
        assert payload.type == "task_completed"
        assert payload.session_id == "agent-0001"
        assert payload.title == "Task Completed"
        assert payload.body == "Your task has been completed successfully."

    def test_requires_type(self):
        """typeが必須であることを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            WebhookPayload(
                session_id="agent-0001",
                title="Test",
                body="Body",
            )

        assert "type" in str(exc_info.value).lower()

    def test_requires_session_id(self):
        """session_idが必須であることを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            WebhookPayload(
                type="task_completed",
                title="Test",
                body="Body",
            )

        assert "session_id" in str(exc_info.value).lower()

    def test_title_min_length_validation(self):
        """titleの最小長バリデーションが動作することを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            WebhookPayload(
                type="task_completed",
                session_id="agent-0001",
                title="",
                body="Body",
            )

        assert "at least 1 character" in str(exc_info.value).lower()

    def test_title_max_length_validation(self):
        """titleの最大長バリデーションが動作することを確認する。"""
        # Arrange
        long_title = "a" * 101

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            WebhookPayload(
                type="task_completed",
                session_id="agent-0001",
                title=long_title,
                body="Body",
            )

        assert "at most 100 character" in str(exc_info.value).lower()

    def test_body_min_length_validation(self):
        """bodyの最小長バリデーションが動作することを確認する。"""
        # Arrange & Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            WebhookPayload(
                type="task_completed",
                session_id="agent-0001",
                title="Title",
                body="",
            )

        assert "at least 1 character" in str(exc_info.value).lower()

    def test_body_max_length_validation(self):
        """bodyの最大長バリデーションが動作することを確認する。"""
        # Arrange
        long_body = "a" * 501

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            WebhookPayload(
                type="task_completed",
                session_id="agent-0001",
                title="Title",
                body=long_body,
            )

        assert "at most 500 character" in str(exc_info.value).lower()
