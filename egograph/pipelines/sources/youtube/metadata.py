"""YouTube metadata resolution helpers."""

import logging

import requests

from pipelines.sources.youtube.api_client import QuotaExceededError, YouTubeAPIClient
from pipelines.sources.youtube.canonical import (
    transform_channel_info,
    transform_video_info,
)
from pipelines.sources.youtube.storage import YouTubeStorage

logger = logging.getLogger(__name__)


def build_video_master_rows(
    api_videos: list[dict],
    content_type_map: dict[str, str],
) -> list[dict]:
    """YouTube API video レスポンスから canonical video master 行を構築する。"""
    rows: list[dict] = []
    for video in api_videos:
        canonical = transform_video_info(video)
        canonical["content_type"] = content_type_map.get(canonical["video_id"], "video")
        rows.append(canonical)
    return rows


def build_channel_master_rows(api_channels: list[dict]) -> list[dict]:
    """YouTube API channel レスポンスから canonical channel master 行を構築する。"""
    return [transform_channel_info(channel) for channel in api_channels]


def enrich_watch_events_with_metadata(
    events: list[dict],
    video_master: list[dict],
    channel_master: list[dict],
) -> list[dict]:
    """watch event に canonical master のメタデータを反映する。"""
    videos_by_id = {row["video_id"]: row for row in video_master}
    channels_by_id = {row["channel_id"]: row for row in channel_master}
    enriched: list[dict] = []
    for event in events:
        video = videos_by_id.get(event["video_id"])
        if video is None:
            enriched.append(event)
            continue
        channel = channels_by_id.get(video.get("channel_id"))
        enriched.append(
            {
                **event,
                "video_title": video.get("title") or event["video_title"],
                "channel_id": video.get("channel_id") or event["channel_id"],
                "channel_name": (
                    (channel.get("channel_name") if channel is not None else None)
                    or video.get("channel_name")
                    or event["channel_name"]
                ),
            }
        )
    return enriched


def resolve_youtube_metadata(
    events: list[dict],
    api_client: YouTubeAPIClient,
) -> tuple[list[dict], list[dict], list[dict]] | None:
    """watch event に対して YouTube Data API メタデータを解決する。"""
    if not events:
        return [], [], []

    content_type_map = {
        event["video_id"]: event.get("content_type", "video") for event in events
    }
    video_ids = sorted({event["video_id"] for event in events})
    try:
        api_videos = api_client.get_videos(video_ids)
    except (QuotaExceededError, requests.RequestException):
        logger.exception("YouTube metadata fetch failed while loading videos")
        return None
    video_master = build_video_master_rows(api_videos, content_type_map)
    channel_ids = sorted(
        {
            row["channel_id"]
            for row in video_master
            if isinstance(row.get("channel_id"), str)
        }
    )
    try:
        api_channels = api_client.get_channels(channel_ids) if channel_ids else []
    except (QuotaExceededError, requests.RequestException):
        logger.exception("YouTube metadata fetch failed while loading channels")
        return None

    channel_master = build_channel_master_rows(api_channels)
    enriched = enrich_watch_events_with_metadata(events, video_master, channel_master)
    return enriched, video_master, channel_master


def save_youtube_masters(
    storage: YouTubeStorage,
    video_rows: list[dict],
    channel_rows: list[dict],
) -> bool:
    """video / channel master snapshot を保存する。"""
    video_key = True
    channel_key = True
    if video_rows:
        video_key = storage.save_video_master(video_rows) is not None
    if channel_rows:
        channel_key = storage.save_channel_master(channel_rows) is not None
    return video_key and channel_key
