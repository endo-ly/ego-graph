"""YouTube固有の設定。"""

from dataclasses import dataclass
from typing import Any

# レート制限
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2  # 指数バックオフ: 2, 4, 8秒

# MyActivityスクレイピング設定
SCROLL_DELAY_MIN = 2  # 秒
SCROLL_DELAY_MAX = 5  # 秒
MYACTIVITY_URL = "https://myactivity.google.com/product/youtube"
TIMEZONE = "UTC"

# YouTube Data API設定
YOUTUBE_API_BATCH_SIZE = 50  # API制限: videos.list, channels.listは50件/リクエスト
YOUTUBE_API_QUOTA_PER_DAY = 10000  # 1日のクォータ上限


@dataclass(frozen=True)
class AccountConfig:
    """Googleアカウント設定。

    Args:
        account_id: アカウント識別子(例: account1, account2)
        cookies: Playwright Cookieオブジェクトのリスト
        youtube_api_key: YouTube Data API v3のAPIキー
    """

    account_id: str
    cookies: list[dict[str, Any]]
    youtube_api_key: str
