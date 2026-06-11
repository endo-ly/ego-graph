"""Google Health 接続のドメインモデル。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ConnectionStatus(StrEnum):
    """Google Health connection の状態。"""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


@dataclass(frozen=True)
class GoogleHealthConnection:
    """Google Health connection metadata。"""

    connection_id: str
    status: ConnectionStatus
    scopes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    last_error_message: str | None


@dataclass(frozen=True)
class OAuthToken:
    """復号済み OAuth token。"""

    access_token: str
    refresh_token: str
    expires_at: datetime
    token_type: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class EncryptedOAuthToken:
    """SQLite に保存する暗号化済み OAuth token。"""

    connection_id: str
    access_token_encrypted: bytes
    refresh_token_encrypted: bytes
    expires_at: datetime
    token_type: str
    updated_at: datetime
