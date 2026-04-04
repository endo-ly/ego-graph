"""YouTube視聴履歴 → R2 (Parquet Data Lake) データ取り込みパイプライン。"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from pipelines.sources.common.settings import PipelinesSettings
from pipelines.sources.common.utils import log_execution_time
from pipelines.sources.google_activity import transform as google_transform
from pipelines.sources.google_activity.config import AccountConfig
from pipelines.sources.google_activity.pipeline import run_all_accounts_pipeline
from pipelines.sources.google_activity.storage import YouTubeStorage

logger = logging.getLogger(__name__)


@log_execution_time
def main():
    """メイン Ingestion パイプライン実行処理。"""
    # 設定を先にロードしてログ設定を初期化
    config = PipelinesSettings.load()

    logger.info("=" * 60)
    logger.info("EgoGraph YouTube Activity Ingestion Pipeline (Parquet)")
    logger.info(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    try:
        # Google Activityアカウント設定の構築
        accounts = _load_google_accounts()

        # R2 Storage初期化
        r2_config = config.duckdb.r2 if config.duckdb else None
        if not r2_config:
            raise ValueError("R2 config is required for YouTube Activity pipeline")

        storage = YouTubeStorage(
            endpoint_url=r2_config.endpoint_url,
            access_key_id=r2_config.access_key_id,
            secret_access_key=r2_config.secret_access_key.get_secret_value(),
            bucket_name=r2_config.bucket_name,
            raw_path=r2_config.raw_path,
            events_path=r2_config.events_path,
            master_path=r2_config.master_path,
        )

        # デフォルト設定
        # 過去1ヶ月分の視聴履歴を取得
        after_timestamp = datetime.now(timezone.utc) - timedelta(days=30)
        max_items = 1000

        # パイプライン実行
        results = asyncio.run(
            run_all_accounts_pipeline(
                accounts=accounts,
                storage=storage,
                transform=google_transform,
                after_timestamp=after_timestamp,
                max_items=max_items,
            )
        )

        # 結果の集計
        success_count = sum(1 for r in results.values() if r.success)
        total_count = len(results)

        if success_count == total_count:
            logger.info(
                "All accounts pipeline succeeded (%d/%d)", success_count, total_count
            )
        else:
            logger.warning(
                "Some accounts failed: %d/%d succeeded", success_count, total_count
            )

        # 失敗したアカウントがある場合はエラー終了
        if success_count < total_count:
            sys.exit(1)

    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)


def _load_google_accounts() -> list[AccountConfig]:
    """環境変数からGoogleアカウント設定を読み込む。

    Returns:
        AccountConfigのリスト

    環境変数:
        YOUTUBE_API_KEY: YouTube Data API v3 のAPIキー（全アカウント共通）
        GOOGLE_COOKIE_ACCOUNT1: アカウント1のCookie（JSON形式またはファイルパス）
        GOOGLE_COOKIE_ACCOUNT2: アカウント2のCookie（任意）

    Note:
        Cookieは JSON文字列 または key=value,key=value 形式で指定する
    """
    accounts = []

    # YouTube API Key（全アカウント共通）
    youtube_api_key = os.getenv("YOUTUBE_API_KEY")
    if not youtube_api_key:
        raise ValueError("YOUTUBE_API_KEY is required")

    # アカウント1（必須）
    cookies_1 = _load_cookies("GOOGLE_COOKIE_ACCOUNT1")
    if cookies_1:
        accounts.append(
            AccountConfig(
                account_id="account1",
                cookies=cookies_1,
                youtube_api_key=youtube_api_key,
            )
        )

    # アカウント2（任意）
    cookies_2 = _load_cookies("GOOGLE_COOKIE_ACCOUNT2")
    if cookies_2:
        accounts.append(
            AccountConfig(
                account_id="account2",
                cookies=cookies_2,
                youtube_api_key=youtube_api_key,
            )
        )

    if not accounts:
        raise ValueError("At least one account (GOOGLE_COOKIE_ACCOUNT1) is required")

    logger.info("Loaded %d Google account(s)", len(accounts))

    return accounts


def _load_cookies(env_var: str) -> list[dict] | None:
    """環境変数からCookieを読み込む。

    Args:
        env_var: 環境変数名（例: GOOGLE_COOKIE_ACCOUNT1）

    Returns:
        Cookieオブジェクトのリスト。環境変数が未設定の場合はNone

    Raises:
        ValueError: Cookieのパースに失敗した場合
    """
    cookies_str = os.getenv(env_var)
    # 未設定の場合はNoneを返す（空文字列はエラーにするため区別）
    if cookies_str is None:
        return None

    # JSON文字列または key=value,key=value 形式としてパース
    try:
        first_char = cookies_str.lstrip()[0] if cookies_str.lstrip() else ""
        if first_char in ["{", "["]:
            parsed = json.loads(cookies_str)
            return _normalize_cookies(parsed)
        # key=value,key=value形式のパース
        cookies = []
        for pair in cookies_str.split(","):
            if "=" in pair:
                key, value = pair.strip().split("=", 1)
                cookies.append({"name": key.strip(), "value": value.strip()})
        # 少なくとも1つのcookieがパースされたことを検証
        if not cookies:
            value_preview = cookies_str[:100]
            raise ValueError(
                f"invalid_cookies: no valid key=value pairs found in {env_var} "
                f"(value: {value_preview}...)"
            )
        return _normalize_cookies(cookies)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to parse {env_var}: {e}") from e


def _normalize_cookies(parsed: object) -> list[dict]:
    """Cookie入力を正規化し、Playwright必須属性を補完する。"""
    if isinstance(parsed, dict):
        cookies = [{"name": k, "value": v} for k, v in parsed.items()]
    elif isinstance(parsed, list):
        cookies = []
        for idx, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise ValueError(
                    f"invalid_cookie_list_item: element {idx} is not a dict "
                    f"(got {type(item).__name__})"
                )
            if "name" not in item or "value" not in item:
                raise ValueError(
                    "invalid_cookie_list_item: element "
                    f"{idx} missing required keys 'name' or 'value'"
                )
            cookie = dict(item)
            cookie["name"] = str(cookie["name"]).strip()
            cookie["value"] = str(cookie["value"]).strip()
            cookies.append(cookie)
    else:
        raise ValueError("JSON must be a dict or list of cookie objects")

    for cookie in cookies:
        has_url = "url" in cookie and str(cookie["url"]).strip() != ""
        has_domain = "domain" in cookie and str(cookie["domain"]).strip() != ""
        has_path = "path" in cookie and str(cookie["path"]).strip() != ""

        # urlがない場合のみdomain/pathを補完（既存値は尊重）
        if not has_url:
            if not has_domain:
                cookie["domain"] = ".google.com"
            if not has_path:
                cookie["path"] = "/"

        # sameSite を設定（Playwright 推奨、既存値は尊重）
        if "sameSite" not in cookie:
            cookie["sameSite"] = "Lax"

    return cookies


if __name__ == "__main__":
    main()
