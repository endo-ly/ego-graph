import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from pipelines.sources.youtube.canonical import (
    transform_channel_info,
    transform_video_info,
)

logger = logging.getLogger(__name__)


def _generate_watch_id(account_id: str, video_id: str, watched_at: Any) -> str:
    """視聴履歴のユニークIDを生成する。

    Args:
        account_id: アカウントID
        video_id: 動画ID
        watched_at: 視聴日時

    Returns:
        watch_id (sha256 hash[:16])
    """
    hash_input = f"{account_id}_{video_id}_{watched_at}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def _parse_iso8601(timestamp_str: str) -> datetime | None:
    """ISO8601形式のタイムスタンプをdatetimeに変換する。

    Args:
        timestamp_str: ISO8601形式のタイムスタンプ文字列

    Returns:
        datetimeオブジェクト（UTC）、またはパース失敗時はNone
    """
    if not timestamp_str:
        return None

    try:
        parsed = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def transform_watch_history_item(
    item: dict[str, Any], account_id: str
) -> dict[str, Any] | None:
    """MyActivityから取得した視聴履歴アイテムをイベント形式に変換する。

    Args:
        item: MyActivityコレクターから返されたアイテム辞書
        account_id: アカウントID ('account1' or 'account2')

    Returns:
        変換されたイベント辞書、または必須フィールドが欠けている場合はNone

    必須フィールド:
        - video_id: 動画ID（空でないこと）
        - title: 動画タイトル
        - channel_name: チャンネル名
        - watched_at: 視聴日時（datetimeオブジェクト）
    """
    # 必須フィールドのチェック
    video_id = item.get("video_id")
    title = item.get("title")
    channel_name = item.get("channel_name")
    watched_at = item.get("watched_at")

    if not all([video_id, title, channel_name, watched_at]):
        return None

    # video_idが空文字列の場合も無効
    if not video_id or not isinstance(video_id, str):
        return None

    # watched_atの検証と変換（文字列の場合はdatetimeにパース）
    if isinstance(watched_at, str):
        parsed = _parse_iso8601(watched_at)
        if parsed is None:
            logger.warning(
                "invalid_watched_at: failed to parse datetime string '%s' "
                "for video_id=%s",
                watched_at,
                video_id,
            )
            return None
        watched_at = parsed
    elif not isinstance(watched_at, datetime):
        logger.warning(
            "invalid_watched_at: unsupported type %s for video_id=%s",
            type(watched_at).__name__,
            video_id,
        )
        return None

    return {
        "watch_id": _generate_watch_id(account_id, video_id, watched_at),
        "account_id": account_id,
        "watched_at_utc": watched_at,
        "video_id": video_id,
        "video_title": title,
        "channel_id": None,  # MyActivityには含まれない
        "channel_name": channel_name,
        "video_url": item.get("video_url"),
        "context": None,  # オプションフィールド
    }


def transform_watch_history_items(
    items: list[dict[str, Any]], account_id: str
) -> list[dict[str, Any]]:
    """MyActivityから取得した視聴履歴リストをイベント形式に変換する。

    Args:
        items: MyActivityコレクターから返されたアイテムリスト
        account_id: アカウントID ('account1' or 'account2')

    Returns:
        変換されたイベントデータのリスト（無効なアイテムは除外）
    """
    events = []
    for item in items:
        event = transform_watch_history_item(item, account_id)
        if event:
            events.append(event)
    return events

