"""YouTube watch event 抽出ロジック。

Browser History の page view rows から YouTube 視聴イベントを抽出・正規化する。
"""

import uuid
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

_WATCH_EVENT_PREFIX = "youtube_watch_event_"


def normalize_youtube_url(url: str) -> str | None:
    """YouTube URL を正規化する。youtu.be 短縮URLを標準 watch URL へ変換する。

    Args:
        url: 対象URL文字列。

    Returns:
        正規化済みURL。非YouTube URLの場合は None。
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if host == "youtu.be" or host == "www.youtu.be":
        video_id = parsed.path.lstrip("/")
        if not video_id:
            return None
        return f"https://www.youtube.com/watch?v={video_id}"

    if host in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        return url

    return None


def extract_video_id(url: str) -> str | None:
    """YouTube URL から video_id を抽出する。

    watch?v=, shorts/, youtu.be/ の各形式に対応する。
    channel / playlist / feed / search / home は None を返す。

    Args:
        url: 対象URL文字列。

    Returns:
        抽出された video_id。対象外URLの場合は None。
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path

    is_youtube = host in (
        "www.youtube.com",
        "youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
    )
    if not is_youtube:
        return None

    # youtu.be/VIDEO_ID
    if host in ("youtu.be", "www.youtu.be"):
        video_id = path.lstrip("/")
        return video_id if video_id else None

    # shorts/VIDEO_ID
    if path.startswith("/shorts/"):
        video_id = path.split("/")[2] if len(path.split("/")) > 2 else None
        return video_id if video_id else None

    # watch?v=VIDEO_ID
    if path == "/watch":
        query_params = parse_qs(parsed.query)
        video_ids = query_params.get("v")
        if video_ids:
            return video_ids[0]

    return None


def detect_content_type(url: str) -> str:
    """URL から YouTube コンテンツタイプを判定する。

    Args:
        url: 対象URL文字列。

    Returns:
        "video" または "short"。
    """
    parsed = urlparse(url)
    if parsed.path.startswith("/shorts/"):
        return "short"
    return "video"


def extract_youtube_watch_events(
    page_view_rows: list[dict],
) -> list[dict]:
    """page_view_rows から YouTube watch event を抽出する。

    YouTube の watch URL (watch?v=, shorts/, youtu.be/) のみを対象とする。
    title が欠落している行は除外する。

    Args:
        page_view_rows: transform_payload_to_page_view_rows の出力。

    Returns:
        YouTube watch event のリスト。
    """
    events: list[dict] = []

    for row in page_view_rows:
        url = row.get("url", "")
        title = row.get("title")

        normalized = normalize_youtube_url(url)
        if normalized is None:
            continue

        video_id = extract_video_id(url)
        if video_id is None:
            continue

        if not title:
            continue

        # youtu.be の場合、正規URLを video_url として使用
        video_url = normalized

        started_at = row["started_at_utc"]
        ingested_at = row["ingested_at_utc"]

        source_event_id = row["page_view_id"]
        watch_event_uuid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"browser_history:{source_event_id}:{video_id}",
        )

        events.append(
            {
                "watch_event_id": f"{_WATCH_EVENT_PREFIX}{watch_event_uuid}",
                "watched_at_utc": started_at,
                "video_id": video_id,
                "video_url": video_url,
                "video_title": title,
                "channel_id": None,
                "channel_name": None,
                "content_type": detect_content_type(url),
                "source": "browser_history",
                "source_event_id": source_event_id,
                "source_device": row["source_device"],
                "ingested_at_utc": ingested_at,
            }
        )

    return events


def group_watch_events_by_month(
    events: list[dict],
) -> dict[tuple[int, int], list[dict]]:
    """watch event を (year, month) 単位でグルーピングする。

    Args:
        events: extract_youtube_watch_events の出力。

    Returns:
        キーが (year, month)、値が該当月のイベントリスト。
    """
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for event in events:
        watched_at = event["watched_at_utc"]
        grouped[(watched_at.year, watched_at.month)].append(event)
    return dict(grouped)
