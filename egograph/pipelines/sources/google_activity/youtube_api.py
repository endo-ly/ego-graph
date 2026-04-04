import logging
import time
from typing import Any

import requests

from pipelines.sources.google_activity.config import (
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    YOUTUBE_API_BATCH_SIZE,
)

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """YouTube API のクォータ超過エラー。"""

    pass


class YouTubeAPIClient:
    """YouTube Data API v3 クライアント。

    Args:
        api_key: YouTube Data API v3 の API キー
    """

    def __init__(self, api_key: str) -> None:
        """クライアントを初期化する。

        Args:
            api_key: YouTube Data API v3 の API キー
        """
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        logger.info("Initialized YouTubeAPIClient")

    def _make_request_with_retry(
        self, url: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """リトライロジック付きで API リクエストを行う。

        Args:
            url: リクエストURL
            params: リクエストパラメータ

        Returns:
            API レスポンスの JSON データ

        Raises:
            QuotaExceededError: クォータ超過時
            requests.HTTPError: HTTP エラー時
        """
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, params=params, timeout=30)

                # クォータ超過エラーチェック (403の場合は先にチェック)
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
                        # JSON解析エラーの場合は後のraise_for_statusで処理
                        pass

                response.raise_for_status()

                data = response.json()

                return data

            except QuotaExceededError:
                # クォータ超過はリトライせず、即座に例外を再スロー
                raise
            except (
                requests.HTTPError,
                requests.ConnectionError,
                requests.Timeout,
            ) as e:
                if attempt < MAX_RETRIES - 1:
                    # 指数バックオフで待機
                    wait_time = RETRY_BACKOFF_FACTOR**attempt
                    logger.warning(
                        "Request failed (attempt %d/%d): %s. Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES,
                        e,
                        wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    # 最後の試行で失敗した場合
                    logger.exception(
                        "Request failed after %d attempts: %s", MAX_RETRIES, e
                    )
                    raise

        raise requests.HTTPError("Max retries exceeded")  # pragma: no cover

    def _batch_request(
        self, endpoint: str, ids: list[str], part: str
    ) -> list[dict[str, Any]]:
        """ID リストをバッチ処理して API リクエストを行う。

        Args:
            endpoint: API エンドポイント（例: "videos"）
            ids: 動画IDまたはチャンネルIDのリスト
            part: 取得するデータパート（例: "snippet,statistics"）

        Returns:
            すべてのバッチの結果を結合したリスト
        """
        if not ids:
            return []

        all_items: list[dict[str, Any]] = []

        # IDリストをバッチサイズに分割
        for i in range(0, len(ids), YOUTUBE_API_BATCH_SIZE):
            batch_ids = ids[i : i + YOUTUBE_API_BATCH_SIZE]
            ids_str = ",".join(batch_ids)

            logger.debug(
                "Fetching %s (batch %d/%d): %s",
                endpoint,
                (i // YOUTUBE_API_BATCH_SIZE) + 1,
                (len(ids) + YOUTUBE_API_BATCH_SIZE - 1) // YOUTUBE_API_BATCH_SIZE,
                ids_str,
            )

            url = "%s/%s" % (self.base_url, endpoint)
            params = {
                "key": self.api_key,
                "id": ids_str,
                "part": part,
            }

            data = self._make_request_with_retry(url, params)

            # items がない場合（空の結果）を考慮
            items = data.get("items", [])
            all_items.extend(items)

            # レート制限を考慮して少し待機
            time.sleep(0.1)

        return all_items

    def get_videos(self, video_ids: list[str]) -> list[dict[str, Any]]:
        """動画情報を取得する。

        Args:
            video_ids: 動画IDのリスト

        Returns:
            動画情報の辞書リスト

        Raises:
            QuotaExceededError: クォータ超過時
            requests.HTTPError: HTTP エラー時

        Example:
            >>> client = YouTubeAPIClient(api_key="your_key")
            >>> videos = client.get_videos(["video1", "video2"])
        """
        logger.info("Fetching %d videos", len(video_ids))

        # 取得するパートを指定
        part = "snippet,statistics,contentDetails"

        return self._batch_request("videos", video_ids, part)

    def get_channels(self, channel_ids: list[str]) -> list[dict[str, Any]]:
        """チャンネル情報を取得する。

        Args:
            channel_ids: チャンネルIDのリスト

        Returns:
            チャンネル情報の辞書リスト

        Raises:
            QuotaExceededError: クォータ超過時
            requests.HTTPError: HTTP エラー時

        Example:
            >>> client = YouTubeAPIClient(api_key="your_key")
            >>> channels = client.get_channels(["channel1", "channel2"])
        """
        logger.info("Fetching %d channels", len(channel_ids))

        # 取得するパートを指定
        part = "snippet,statistics,brandingSettings"

        return self._batch_request("channels", channel_ids, part)
