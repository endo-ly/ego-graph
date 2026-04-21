"""YouTube メタデータ解決・マスター保存。

Browser History から抽出した watch event に YouTube Data API v3 の
動画・チャンネルメタデータを付与し、video / channel master を保存する。
"""

import logging
from datetime import datetime, timezone

from pipelines.sources.browser_history.storage import BrowserHistoryStorage
from pipelines.sources.google_activity.transform import (
    transform_channel_info,
    transform_video_info,
)
from pipelines.sources.google_activity.youtube_api import YouTubeAPIClient

logger = logging.getLogger(__name__)


def build_video_master_rows(
    api_videos: list[dict],
    content_type_map: dict[str, str],
) -> list[dict]:
    """YouTube API video レスポンスから video master 行を構築する。

    Args:
        api_videos: YouTubeAPIClient.get_videos() のレスポンス。
        content_type_map: video_id → content_type ("video" / "short") の対応。

    Returns:
        video master 行のリスト。
    """
    rows: list[dict] = []
    now = datetime.now(timezone.utc)
    for video in api_videos:
        transformed = transform_video_info(video)
        video_id = transformed["video_id"]
        rows.append(
            {
                "video_id": video_id,
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "video_title": transformed["title"],
                "channel_id": transformed["channel_id"],
                "channel_name": transformed["channel_name"],
                "content_type": content_type_map.get(video_id, "video"),
                "updated_at_utc": now,
            }
        )
    return rows


def build_channel_master_rows(api_channels: list[dict]) -> list[dict]:
    """YouTube API channel レスポンスから channel master 行を構築する。

    Args:
        api_channels: YouTubeAPIClient.get_channels() のレスポンス。

    Returns:
        channel master 行のリスト。
    """
    rows: list[dict] = []
    now = datetime.now(timezone.utc)
    for channel in api_channels:
        transformed = transform_channel_info(channel)
        rows.append(
            {
                "channel_id": transformed["channel_id"],
                "channel_name": transformed["channel_name"],
                "updated_at_utc": now,
            }
        )
    return rows


def enrich_watch_events_with_metadata(
    events: list[dict],
    video_master: list[dict],
) -> list[dict]:
    """watch event に video master のメタデータを反映する。

    video_id を join key として、video_title / channel_id / channel_name を付与する。

    Args:
        events: 抽出済み watch event リスト。
        video_master: build_video_master_rows の出力。

    Returns:
        メタデータが反映された watch event リスト（新しいリスト）。
    """
    lookup = {row["video_id"]: row for row in video_master}
    enriched: list[dict] = []
    for event in events:
        video_id = event["video_id"]
        master = lookup.get(video_id)
        if master is None:
            enriched.append(event)
            continue
        enriched.append(
            {
                **event,
                "video_title": master["video_title"],
                "channel_id": master["channel_id"],
                "channel_name": master["channel_name"],
            }
        )
    return enriched


def resolve_youtube_metadata(
    events: list[dict],
    api_client: YouTubeAPIClient,
) -> tuple[list[dict], list[dict], list[dict]] | None:
    """watch event に対して YouTube Data API メタデータを解決する。

    1. events から unique video_ids を抽出
    2. get_videos → video master 構築
    3. video レスポンスから unique channel_ids を抽出
    4. get_channels → channel master 構築
    5. events にメタデータを反映

    Args:
        events: 抽出済み watch event リスト。
        api_client: 初期化済み YouTubeAPIClient。

    Returns:
        (enriched_events, video_master_rows, channel_master_rows)。
        API エラー時は None。
    """
    if not events:
        return [], [], []

    # unique video_ids
    video_ids = list({e["video_id"] for e in events})
    # content_type map (latest wins for duplicates)
    content_type_map: dict[str, str] = {}
    for e in events:
        content_type_map[e["video_id"]] = e.get("content_type", "video")

    try:
        api_videos = api_client.get_videos(video_ids)
    except Exception:
        logger.exception("Failed to resolve YouTube video metadata")
        return None

    video_master = build_video_master_rows(api_videos, content_type_map)

    # unique channel_ids from API response
    channel_ids = list(
        {v["channel_id"] for v in video_master if v["channel_id"]}
    )

    try:
        api_channels = api_client.get_channels(channel_ids)
    except Exception:
        logger.exception("Failed to resolve YouTube channel metadata")
        return None

    channel_master = build_channel_master_rows(api_channels)

    enriched = enrich_watch_events_with_metadata(events, video_master)

    return enriched, video_master, channel_master


def save_youtube_masters(
    storage: BrowserHistoryStorage,
    video_rows: list[dict],
    channel_rows: list[dict],
) -> bool:
    """video / channel master parquet を保存する。

    Args:
        storage: BrowserHistoryStorage インスタンス。
        video_rows: build_video_master_rows の出力。
        channel_rows: build_channel_master_rows の出力。

    Returns:
        両方の保存に成功した場合 True。
    """
    now = datetime.now(timezone.utc)
    video_key = storage.save_parquet(
        video_rows,
        year=now.year,
        month=now.month,
        prefix="master/youtube/videos",
    )
    channel_key = storage.save_parquet(
        channel_rows,
        year=now.year,
        month=now.month,
        prefix="master/youtube/channels",
    )
    return video_key is not None and channel_key is not None
