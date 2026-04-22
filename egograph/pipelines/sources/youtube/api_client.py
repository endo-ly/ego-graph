"""YouTube Data API v3 client."""

import logging
import time
from typing import Any

import requests

from pipelines.sources.youtube.config import (
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    YOUTUBE_API_BATCH_SIZE,
)

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """YouTube API のクォータ超過エラー。"""


class YouTubeAPIClient:
    """YouTube Data API v3 クライアント。"""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        logger.info("Initialized YouTubeAPIClient")

    def _make_request_with_retry(
        self, url: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """リトライロジック付きで API リクエストを行う。"""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, params=params, timeout=30)
                if response.status_code == 403:
                    try:
                        data = response.json()
                        if "error" in data:
                            error = data["error"]
                            for error_detail in error.get("errors", []):
                                if error_detail.get("reason") == "quotaExceeded":
                                    raise QuotaExceededError(
                                        "YouTube API quota exceeded: %s"
                                        % error.get("message", "Unknown reason")
                                    )
                    except ValueError:
                        pass

                response.raise_for_status()
                return response.json()
            except QuotaExceededError:
                raise
            except (
                requests.HTTPError,
                requests.ConnectionError,
                requests.Timeout,
            ) as exc:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_FACTOR**attempt
                    logger.warning(
                        "Request failed (attempt %d/%d): %s. Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES,
                        exc,
                        wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    logger.exception(
                        "Request failed after %d attempts: %s", MAX_RETRIES, exc
                    )
                    raise

        raise requests.HTTPError("Max retries exceeded")  # pragma: no cover

    def _batch_request(
        self, endpoint: str, ids: list[str], part: str
    ) -> list[dict[str, Any]]:
        """ID リストをバッチ処理して API リクエストを行う。"""
        if not ids:
            return []

        all_items: list[dict[str, Any]] = []
        for index in range(0, len(ids), YOUTUBE_API_BATCH_SIZE):
            batch_ids = ids[index : index + YOUTUBE_API_BATCH_SIZE]
            logger.debug(
                "Fetching %s (batch %d/%d): %s",
                endpoint,
                (index // YOUTUBE_API_BATCH_SIZE) + 1,
                (len(ids) + YOUTUBE_API_BATCH_SIZE - 1) // YOUTUBE_API_BATCH_SIZE,
                ",".join(batch_ids),
            )
            data = self._make_request_with_retry(
                f"{self.base_url}/{endpoint}",
                {
                    "key": self.api_key,
                    "id": ",".join(batch_ids),
                    "part": part,
                },
            )
            all_items.extend(data.get("items", []))
            time.sleep(0.1)
        return all_items

    def get_videos(self, video_ids: list[str]) -> list[dict[str, Any]]:
        """動画情報を取得する。"""
        logger.info("Fetching %d videos", len(video_ids))
        return self._batch_request(
            "videos",
            video_ids,
            "snippet,statistics,contentDetails",
        )

    def get_channels(self, channel_ids: list[str]) -> list[dict[str, Any]]:
        """チャンネル情報を取得する。"""
        logger.info("Fetching %d channels", len(channel_ids))
        return self._batch_request(
            "channels",
            channel_ids,
            "snippet,statistics,brandingSettings",
        )


__all__ = ["QuotaExceededError", "YouTubeAPIClient"]
