"""Google Healthのドメインモデル。"""

from dataclasses import dataclass
from datetime import date, datetime
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


class GoogleHealthRunMode(StrEnum):
    """Google Health取り込みの実行モード。"""

    INITIAL_BACKFILL = "initial_backfill"
    RANGE = "range"
    DATA_TYPE_RANGE = "data_type_range"


class SyncStatus(StrEnum):
    """data type単位の同期結果。"""

    SUCCESS = "success"
    NO_DATA = "no_data"
    FAILED = "failed"


@dataclass(frozen=True)
class GoogleHealthIngestRequest:
    """Google Health取り込みrunの入力。"""

    mode: GoogleHealthRunMode
    date_from: date
    date_to: date
    data_types: tuple[str, ...]


@dataclass(frozen=True)
class GoogleHealthSyncCursor:
    """data type単位の最終同期結果。"""

    connection_id: str
    data_type: str
    cursor: str | None
    status: SyncStatus
    range_start: date | None
    range_end: date | None
    last_run_id: str | None
    record_count: int
    last_error_message: str | None
    updated_at: datetime
