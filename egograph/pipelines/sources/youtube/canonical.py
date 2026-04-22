"""YouTube canonical transform helpers."""

import re
from datetime import datetime, timezone
from typing import Any


def _parse_iso8601(timestamp_str: str) -> datetime | None:
    """ISO8601形式のタイムスタンプをdatetimeに変換する。"""
    if not timestamp_str:
        return None

    try:
        parsed = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _parse_youtube_duration(duration_str: str) -> int | None:
    """YouTube duration (ISO8601) を秒数に変換する。"""
    if not duration_str or not duration_str.startswith("P"):
        return None

    total_seconds = 0
    day_match = re.search(r"(\d+)D", duration_str)
    if day_match:
        total_seconds += int(day_match.group(1)) * 86400

    t_part = duration_str.split("T", 1)[1] if "T" in duration_str else ""
    hour_match = re.search(r"(\d+)H", t_part)
    if hour_match:
        total_seconds += int(hour_match.group(1)) * 3600

    minute_match = re.search(r"(\d+)M", t_part)
    if minute_match:
        total_seconds += int(minute_match.group(1)) * 60

    second_match = re.search(r"(\d+)S", t_part)
    if second_match:
        total_seconds += int(second_match.group(1))

    return total_seconds


def _get_thumbnail_url(thumbnails: dict[str, Any]) -> str | None:
    """サムネイルURLを優先順位で取得する。"""
    if not thumbnails or not isinstance(thumbnails, dict):
        return None

    for quality in ["high", "medium", "default"]:
        url = thumbnails.get(quality, {}).get("url")
        if url:
            return url
    return None


def _get_safe_int(value: str | None) -> int | None:
    """安全に整数値を取得する。"""
    if not value:
        return None

    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def transform_video_info(video: dict[str, Any]) -> dict[str, Any]:
    """YouTube Data API v3 の動画情報を canonical video master へ変換する。"""
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
    """YouTube Data API v3 のチャンネル情報を canonical channel master へ変換する。"""
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
