"""WebSocketメッセージとドメインモデルの定義。"""

from base64 import b64decode, b64encode
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SessionStatus(str, Enum):
    """セッション状態の列挙型。

    Attributes:
        CONNECTED: 接続可能なセッション
    """

    CONNECTED = "connected"


# ============================================================================
# WebSocket メッセージスキーマ (Client -> Server)
# ============================================================================


class WSInputMessage(BaseModel):
    """クライアントからサーバーへの入力メッセージ。

    端末へのキー入力をBase64エンコードして送信する。
    """

    type: Literal["input"] = Field(default="input", description="メッセージタイプ")
    data_b64: str = Field(..., description="UTF-8エンコードした入力データのBase64")

    def decode_data(self) -> bytes:
        """Base64エンコードされたデータをデコードする。

        Returns:
            デコードされたバイト列
        """
        return b64decode(self.data_b64)

    @field_validator("data_b64")
    @classmethod
    def validate_base64(cls, v: str) -> str:
        """Base64形式のバリデーション。

        Args:
            v: Base64文字列

        Returns:
            検証されたBase64文字列

        Raises:
            ValueError: Base64形式が不正な場合
        """
        try:
            b64decode(v, validate=True)
        except Exception as e:
            raise ValueError(f"Invalid base64 encoding: {e}") from e
        return v


class WSResizeMessage(BaseModel):
    """クライアントからサーバーへの画面サイズ変更メッセージ。

    端末の表示サイズ（列数・行数）を変更する。
    """

    type: Literal["resize"] = Field(default="resize", description="メッセージタイプ")
    cols: int = Field(..., ge=1, le=512, description="端末の列数")
    rows: int = Field(..., ge=1, le=512, description="端末の行数")


class WSScrollMessage(BaseModel):
    """クライアントからサーバーへのスクロールメッセージ。

    スクロールする行数を正負付き整数で送信する。
    負値は上方向、正値は下方向を表す。
    """

    type: Literal["scroll"] = Field(default="scroll", description="メッセージタイプ")
    lines: int = Field(..., ge=-20, le=20, description="スクロール行数")


class WSPingMessage(BaseModel):
    """クライアントからサーバーへのPingメッセージ。

    接続状態を確認するためのハートビート。
    """

    type: Literal["ping"] = Field(default="ping", description="メッセージタイプ")


# ============================================================================
# WebSocket メッセージスキーマ (Server -> Client)
# ============================================================================


class WSOutputMessage(BaseModel):
    """サーバーからクライアントへの出力メッセージ。

    PTYから読み取った生バイト列をBase64エンコードして送信する。
    """

    type: Literal["output"] = Field(default="output", description="メッセージタイプ")
    data_b64: str = Field(..., description="PTY出力のBase64エンコード")
    is_snapshot: bool = Field(False, description="tmuxスナップショット由来かどうか")
    cursor_x: int | None = Field(None, description="カーソルX座標（0始まり）")
    cursor_y: int | None = Field(None, description="カーソルY座標（0始まり）")
    pane_rows: int | None = Field(None, description="表示中ペインの行数")

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        is_snapshot: bool = False,
        cursor_x: int | None = None,
        cursor_y: int | None = None,
        pane_rows: int | None = None,
    ) -> "WSOutputMessage":
        """バイト列から出力メッセージを作成する。

        Args:
            data: PTYから読み取ったバイト列
            cursor_x: カーソルX座標（0始まり）
            cursor_y: カーソルY座標（0始まり）
            pane_rows: 表示中ペインの行数

        Returns:
            Base64エンコードされた出力メッセージ
        """
        return cls(
            data_b64=b64encode(data).decode("ascii"),
            is_snapshot=is_snapshot,
            cursor_x=cursor_x,
            cursor_y=cursor_y,
            pane_rows=pane_rows,
        )


class WSStatusMessage(BaseModel):
    """サーバーからクライアントへの状態変更メッセージ。

    接続状態の変化を通知する。
    """

    type: Literal["status"] = Field(default="status", description="メッセージタイプ")
    state: Literal["connected", "reconnecting", "closed"] = Field(
        ..., description="接続状態"
    )


class WSErrorMessage(BaseModel):
    """サーバーからクライアントへのエラーメッセージ。

    エラーが発生したことを通知する。
    """

    type: Literal["error"] = Field(default="error", description="メッセージタイプ")
    code: str = Field(..., description="エラーコード")
    message: str = Field(..., description="エラーメッセージ")


class WSPongMessage(BaseModel):
    """サーバーからクライアントへのPongメッセージ。

    Pingに対する応答。
    """

    type: Literal["pong"] = Field(default="pong", description="メッセージタイプ")


# ============================================================================
# ドメインモデル
# ============================================================================


class TerminalSession(BaseModel):
    """端末セッションの状態情報。

    Attributes:
        session_id: tmuxセッションID (例: agent-0001)
        activity: 最終アクティブ時刻 (tmuxフォーマット)
        created: セッション作成時刻 (tmuxフォーマット)
    """

    session_id: str = Field(..., description="tmuxセッションID")
    activity: str | None = Field(None, description="最終アクティブ時刻")
    created: str | None = Field(None, description="セッション作成時刻")
    preview_available: bool = Field(False, description="プレビューが利用可能かどうか")
    preview_lines: list[str] = Field(
        default_factory=list,
        description="プレビュー表示用の最新端末行",
    )


class TerminalSnapshotResponse(BaseModel):
    """端末スナップショットレスポンス。"""

    session_id: str = Field(..., description="tmuxセッションID")
    content: str = Field(..., description="キャプチャした端末テキスト")


# ============================================================================
# プッシュ通知モデル
# ============================================================================


class PushNotificationRequest(BaseModel):
    """プッシュ通知リクエストモデル。

    Attributes:
        title: 通知タイトル
        body: 通知本文
        data: 通知データ（オプション）
    """

    title: str = Field(..., min_length=1, max_length=100, description="通知タイトル")
    body: str = Field(..., min_length=1, max_length=500, description="通知本文")
    data: dict[str, str] | None = Field(None, description="通知データ")


class WebhookPayload(BaseModel):
    """Webhookペイロードモデル。

    Attributes:
        type: イベントタイプ（task_completed等）
        session_id: セッションID
        title: 通知タイトル
        body: 通知本文
    """

    type: str = Field(..., description="イベントタイプ")
    session_id: str = Field(..., description="セッションID")
    title: str = Field(..., min_length=1, max_length=100, description="通知タイトル")
    body: str = Field(..., min_length=1, max_length=500, description="通知本文")


class TokenRegistrationRequest(BaseModel):
    """FCMトークン登録リクエストモデル。

    Attributes:
        device_token: FCMデバイストークン
        platform: プラットフォーム（android, ios）
        device_name: デバイス名（オプション）
    """

    device_token: str = Field(..., min_length=1, description="FCMデバイストークン")
    platform: Literal["android", "ios"] = Field(..., description="プラットフォーム")
    device_name: str | None = Field(None, max_length=100, description="デバイス名")
