import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

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


def _parse_youtube_duration(duration_str: str) -> int | None:
    """YouTubeのdurationフォーマット（ISO8601）を秒数に変換する。

    Args:
        duration_str: P1DT2H30M15SやPT2H30M15Sのようなduration文字列

    Returns:
        秒数、またはパース失敗時はNone
    """
    if not duration_str:
        return None

    # Pで始まらない場合は不正
    if not duration_str.startswith("P"):
        return None

    total_seconds = 0

    # 日数 (D) - Tの前
    day_match = re.search(r"(\d+)D", duration_str)
    if day_match:
        total_seconds += int(day_match.group(1)) * 86400

    # T以降の部分を抽出（時分秒）
    t_part = duration_str.split("T", 1)[1] if "T" in duration_str else ""

    # 時間 (H)
    hour_match = re.search(r"(\d+)H", t_part)
    if hour_match:
        total_seconds += int(hour_match.group(1)) * 3600

    # 分 (M)
    minute_match = re.search(r"(\d+)M", t_part)
    if minute_match:
        total_seconds += int(minute_match.group(1)) * 60

    # 秒 (S)
    second_match = re.search(r"(\d+)S", t_part)
    if second_match:
        total_seconds += int(second_match.group(1))

    return total_seconds


def _get_thumbnail_url(thumbnails: dict[str, Any]) -> str | None:
    """サムネイルURLを優先順位で取得する（high > medium > default）。

    Args:
        thumbnails: YouTube APIのthumbnailsオブジェクト

    Returns:
        サムネイルURL、または存在しない場合はNone
    """
    if not thumbnails or not isinstance(thumbnails, dict):
        return None

    # 優先順位: high > medium > default
    for quality in ["high", "medium", "default"]:
        url = thumbnails.get(quality, {}).get("url")
        if url:
            return url

    return None


def _get_safe_int(value: str | None) -> int | None:
    """安全に整数値を取得する。

    Args:
        value: 文字列形式の整数値

    Returns:
        整数値、または変換失敗時はNone
    """
    if not value:
        return None

    try:
        return int(value)
    except (ValueError, TypeError):
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


def transform_video_info(video: dict[str, Any]) -> dict[str, Any]:
    """YouTube Data API v3の動画情報をマスター保存用に変換する。

    Args:
        video: YouTube API (videos.list) の単一videoレスポンス

    Returns:
        変換された動画マスターデータ
    """
    snippet = video.get("snippet", {})
    content_details = video.get("contentDetails", {})
    statistics = video.get("statistics", {})

    return {
        "video_id": video.get("id"),
        "title": snippet.get("title"),
        "channel_id": snippet.get("channelId"),
        "channel_name": snippet.get("channelTitle"),
        "duration_seconds": _parse_youtube_duration(content_details.get("duration")),
        "view_count": _get_safe_int(statistics.get("viewCount")),
        "like_count": _get_safe_int(statistics.get("likeCount")),
        "comment_count": _get_safe_int(statistics.get("commentCount")),
        "published_at": _parse_iso8601(snippet.get("publishedAt")),
        "thumbnail_url": _get_thumbnail_url(snippet.get("thumbnails")),
        "description": snippet.get("description"),
        "category_id": snippet.get("categoryId"),
        "tags": snippet.get("tags"),
        "updated_at": datetime.now(timezone.utc),
    }


def transform_channel_info(channel: dict[str, Any]) -> dict[str, Any]:
    """YouTube Data API v3のチャンネル情報をマスター保存用に変換する。

    Args:
        channel: YouTube API (channels.list) の単一channelレスポンス

    Returns:
        変換されたチャンネルマスターデータ
    """
    snippet = channel.get("snippet", {})
    statistics = channel.get("statistics", {})

    return {
        "channel_id": channel.get("id"),
        "channel_name": snippet.get("title"),
        "subscriber_count": _get_safe_int(statistics.get("subscriberCount")),
        "video_count": _get_safe_int(statistics.get("videoCount")),
        "view_count": _get_safe_int(statistics.get("viewCount")),
        "published_at": _parse_iso8601(snippet.get("publishedAt")),
        "thumbnail_url": _get_thumbnail_url(snippet.get("thumbnails")),
        "description": snippet.get("description"),
        "country": snippet.get("country"),
        "updated_at": datetime.now(timezone.utc),
    }
