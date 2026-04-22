"""YouTube watch event extraction from browser history page views."""

import uuid
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

_WATCH_EVENT_PREFIX = "youtube_watch_event_"


def _extract_youtu_be_video_id(path: str) -> str | None:
    video_id = path.lstrip("/").split("/", 1)[0]
    return video_id or None


def normalize_youtube_url(url: str) -> str | None:
    """YouTube URL を正規化する。"""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if host in ("youtu.be", "www.youtu.be"):
        video_id = _extract_youtu_be_video_id(parsed.path)
        if not video_id:
            return None
        return f"https://www.youtube.com/watch?v={video_id}"

    if host in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        return url

    return None


def extract_video_id(url: str) -> str | None:
    """YouTube URL から video_id を抽出する。"""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path

    if host not in (
        "www.youtube.com",
        "youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
    ):
        return None

    if host in ("youtu.be", "www.youtu.be"):
        return _extract_youtu_be_video_id(path)

    if path.startswith("/shorts/"):
        parts = path.split("/")
        return parts[2] if len(parts) > 2 and parts[2] else None

    if path == "/watch":
        video_ids = parse_qs(parsed.query).get("v")
        if video_ids:
            return video_ids[0]

    return None


def detect_content_type(url: str) -> str:
    """URL から YouTube コンテンツタイプを判定する。"""
    parsed = urlparse(url)
    return "short" if parsed.path.startswith("/shorts/") else "video"


def extract_youtube_watch_events(page_view_rows: list[dict]) -> list[dict]:
    """page_view_rows から YouTube watch event を抽出する。"""
    events: list[dict] = []

    for row in page_view_rows:
        url = row.get("url", "")
        title = row.get("title")
        normalized = normalize_youtube_url(url)
        if normalized is None or not title:
            continue

        video_id = extract_video_id(url)
        if video_id is None:
            continue

        source_event_id = row["page_view_id"]
        watch_event_uuid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"browser_history:{source_event_id}:{video_id}",
        )
        events.append(
            {
                "watch_event_id": f"{_WATCH_EVENT_PREFIX}{watch_event_uuid}",
                "watched_at_utc": row["started_at_utc"],
                "video_id": video_id,
                "video_url": normalized,
                "video_title": title,
                "channel_id": None,
                "channel_name": None,
                "content_type": detect_content_type(url),
                "source": "browser_history",
                "source_event_id": source_event_id,
                "source_device": row["source_device"],
                "ingested_at_utc": row["ingested_at_utc"],
                "browser_history_sync_id": row.get("sync_id"),
            }
        )

    return events


def group_watch_events_by_month(
    events: list[dict],
) -> dict[tuple[int, int], list[dict]]:
    """watch event を month 単位でグルーピングする。"""
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for event in events:
        watched_at = event["watched_at_utc"]
        grouped[(watched_at.year, watched_at.month)].append(event)
    return dict(grouped)
