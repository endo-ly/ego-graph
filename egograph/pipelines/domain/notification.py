"""Pipeline 通知イベントのドメインモデル。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NotificationData:
    """通知イベント固有のデータ。"""

    workflow_id: str
    run_id: str
    error_message: str | None
    custom_message: str | None


@dataclass(frozen=True)
class NotificationEvent:
    """Pipeline から発火する通知イベント。

    CloudEvents v1.0 の構造を参考にした **内部契約** であり、CloudEvents 仕様への
    完全準拠は **目指さない**（必要な場合は adapter 層で正規化する想定）。
    """

    source: str
    type: str
    time: datetime
    data: NotificationData
