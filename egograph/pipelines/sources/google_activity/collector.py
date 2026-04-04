"""MyActivityスクレイパー。

Google MyActivityからYouTube視聴履歴を収集します。
Playwrightを使用してスクレイピングを行い、クッキー認証をサポートします。

壊れやすいポイント (DOM変更に弱い箇所):
- CSSクラス依存: ITEM_CLASS='k2bP7e', TITLE_CLASS='l8sGWb',
  HEADER_SELECTOR='h2, .ot996, .I67SDe'
- 時刻抽出: .WFTFcf の親要素テキストから時刻を抜く（表示形式変更に弱い）
- 日付ヘッダーの紐付け: DOM順にヘッダー→アイテムを読む前提
- 認証判定: URL/テキスト判定（ログイン画面の文言変更に弱い）
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import MAX_RETRIES, MYACTIVITY_URL, RETRY_BACKOFF_FACTOR, TIMEZONE

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """クッキーの期限切れまたは認証エラー。"""

    pass


# 共通リトライデコレータ (AuthenticationErrorはリトライ対象外)
collector_retry = retry(
    retry=retry_if_not_exception_type(AuthenticationError),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=RETRY_BACKOFF_FACTOR, min=2, max=10),
)


def _extract_video_id(video_url: str) -> str | None:
    """YouTube URLからvideo_idを抽出する。

    Args:
        video_url: YouTube動画のURL

    Returns:
        video_id（抽出できない場合はNone）
    """
    if not video_url:
        return None

    # URLパース
    parsed = urlparse(video_url)

    # クエリパラメータからvを抽出
    if parsed.hostname in ["www.youtube.com", "youtube.com", "m.youtube.com"]:
        query_params = parse_qs(parsed.query)
        return query_params.get("v", [None])[0]

    # 短縮URL形式
    if parsed.hostname == "youtu.be":
        return parsed.path.lstrip("/")

    return None


def _parse_watched_at(timestamp_str: str) -> datetime | None:
    """視聴日時文字列をdatetimeオブジェクトに変換する。

    Args:
        timestamp_str: 日時文字列（ISO8601形式など）

    Returns:
        datetimeオブジェクト（UTC）、またはパース失敗時はNone
    """
    # 各種形式を試す
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO8601 with microseconds
        "%Y-%m-%dT%H:%M:%SZ",  # ISO8601 without microseconds
        "%Y-%m-%d %H:%M:%S",  # 簡易形式
        "%Y年%m月%d日 %H:%M",  # 日本語形式
    ]:
        try:
            parsed = datetime.strptime(timestamp_str, fmt)
            # タイムゾーンがない場合はUTCと仮定
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue

    # パースに失敗した場合はNoneを返す
    logger.warning("Failed to parse timestamp: %s", timestamp_str)
    return None


class MyActivityCollector:
    """MyActivityデータコレクター。

    Google MyActivityからYouTube視聴履歴をスクレイピングします。
    Playwrightを使用し、クッキー認証とリトライロジックをサポートします。

    Attributes:
        cookies: Google認証用のクッキーデータ
        browser: Playwrightブラウザインスタンス（遅延初期化）
    """

    def __init__(self, cookies: list[dict[str, Any]]):
        """MyActivityコレクターを初期化します。

        Args:
            cookies: Google認証用クッキー [{"name": "...", "value": "..."}]
        """
        self.cookies = cookies
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._playwright: Playwright | None = None
        logger.info("MyActivity collector initialized with %d cookies", len(cookies))

    async def _initialize_browser(self) -> None:
        """Playwrightブラウザとコンテキストを初期化します。"""
        if self.browser is None or not self.browser.is_connected():
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            playwright_instance = self._playwright
            if playwright_instance is None:
                raise RuntimeError("Failed to initialize Playwright instance")
            self.browser = await playwright_instance.chromium.launch(headless=True)
            browser = self.browser
            if browser is None:
                raise RuntimeError("Browser failed to launch")
            self.context = await browser.new_context(timezone_id="UTC")

            context = self.context
            if context is None:
                raise RuntimeError("Browser context was not created")

            # クッキーを設定
            await context.add_cookies(self.cookies)

            self.page = await context.new_page()
            logger.info("Browser initialized with cookies")

    async def _cleanup_browser(self) -> None:
        """ブラウザリソースをクリーンアップします。"""
        if self.context:
            await self.context.close()
        if self.browser and self.browser.is_connected():
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self.context = None
        self.page = None
        self.browser = None
        logger.info("Browser resources cleaned up")

    @collector_retry
    async def collect_watch_history(
        self,
        after_timestamp: datetime,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        """YouTube視聴履歴を収集します。

        Args:
            after_timestamp: この時刻以降の視聴履歴のみ収集
            max_items: 収集する最大アイテム数（Noneの場合は無制限）

        Returns:
            視聴履歴のリスト。各アイテムは以下のキーを含む:
            - video_id: YouTube動画ID
            - title: 動画タイトル
            - channel_name: チャンネル名
            - watched_at: 視聴日時（datetimeオブジェクト）
            - video_url: 動画URL

        Raises:
            AuthenticationError: クッキーの期限切れまたは認証エラー
        """
        logger.info(
            "Collecting watch history (after=%s, max_items=%s)",
            after_timestamp.isoformat(),
            max_items,
        )

        try:
            await self._initialize_browser()
            page = self.page
            if page is None:
                raise RuntimeError("Browser page is not initialized")

            # MyActivityページにアクセス
            logger.info("Navigating to MyActivity page: %s", MYACTIVITY_URL)
            response = await page.goto(MYACTIVITY_URL, wait_until="networkidle")

            # 認証エラーのチェック
            if await self._is_authentication_failed(response):
                raise AuthenticationError(
                    "Authentication failed. Cookies may be expired or invalid."
                )

            # 視聴履歴アイテムをスクレイピング
            items = await self._scrape_watch_items(after_timestamp, max_items)

            logger.info("Successfully collected %d watch history items", len(items))
            return items

        except AuthenticationError:
            raise
        except Exception as e:
            logger.exception("Failed to collect watch history: %s", e)
            raise
        finally:
            await self._cleanup_browser()

    async def _is_authentication_failed(self, response) -> bool:
        """認証が失敗したかどうかを判定する。

        Args:
            response: ページレスポンスオブジェクト

        Returns:
            認証失敗の場合はTrue
        """
        if response is None:
            return True

        # URLまたはステータスコードで判定
        status_code = response.status
        if status_code in [401, 403]:
            return True

        # リダイレクト先で判定（ログインページへリダイレクトされた場合）
        current_url = self.page.url if self.page else ""
        if "accounts.google.com" in current_url:
            return True

        # ページの内容で判定
        page_content = await self.page.content() if self.page else ""
        if "Sign in" in page_content and "Google Account" in page_content:
            return True

        return False

    async def _scrape_watch_items(
        self,
        after_timestamp: datetime,
        max_items: int | None,
    ) -> list[dict[str, Any]]:
        """視聴履歴アイテムをスクレイピングする。

        Args:
            after_timestamp: この時刻以降の視聴履歴のみ収集
            max_items: 収集する最大アイテム数

        Returns:
            スクレイピングした視聴履歴アイテムのリスト
        """
        page = self.page
        if page is None:
            raise RuntimeError("Browser page is not initialized")

        items: list[dict[str, Any]] = []
        scroll_count = 0
        max_scrolls = 50  # 無限ループ防止

        while scroll_count < max_scrolls:
            # 現在のページのアイテムを抽出
            page_items = await self._extract_items_from_page(after_timestamp)
            new_items = [item for item in page_items if item not in items]
            items.extend(new_items)

            logger.debug(
                "Scroll %d: Found %d new items (total: %d)",
                scroll_count + 1,
                len(new_items),
                len(items),
            )

            # 最大アイテム数に達したら終了
            if max_items is not None and len(items) >= max_items:
                items = items[:max_items]
                break

            # 新しいアイテムが見つからなければ終了
            if len(new_items) == 0:
                logger.info(
                    "No new items found on scroll %d, stopping", scroll_count + 1
                )
                break

            # スクロールしてさらにアイテムを読み込む
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)  # スクロール待機

            scroll_count += 1

        logger.info("Scraped %d items after %d scrolls", len(items), scroll_count)
        return items

    async def _extract_items_from_page(
        self, after_timestamp: datetime
    ) -> list[dict[str, Any]]:
        """現在のページから視聴履歴アイテムを抽出する。

        DOMをJavascriptでトラバースし、日付ヘッダーとアイテムを紐付けて抽出します。

        Args:
            after_timestamp: この時刻以降のアイテムのみ抽出

        Returns:
            抽出したアイテムのリスト
        """
        page = self.page
        if page is None:
            raise RuntimeError("Browser page is not initialized")

        # ページ読み込み完了を待機（アイテムコンテナが表示されるまで）
        try:
            await page.wait_for_selector(".k2bP7e", timeout=10000)
        except Exception:
            logger.warning("Timeout waiting for .k2bP7e selector")
            # タイムアウトでもDOM解析は試みる

        # JavascriptでDOMを解析してデータ抽出
        scraped_data = await page.evaluate(
            """
            () => {
                const results = [];
                let currentDate = "";
                
                const ITEM_CLASS = 'k2bP7e';
                const TITLE_CLASS = 'l8sGWb';
                
                const HEADER_SELECTOR = 'h2, .ot996, .I67SDe';
                const nodes = document.querySelectorAll(
                    `${HEADER_SELECTOR}, .${ITEM_CLASS}`
                );
                
                if (nodes.length === 0) return [];
                
                for (const node of nodes) {
                    try {
                        if (node.matches(HEADER_SELECTOR)) {
                            currentDate = node.innerText;
                            continue;
                        }

                        if (!node.classList.contains(ITEM_CLASS)) {
                            continue;
                        }

                        if (!currentDate) {
                            continue;
                        }
                        const titleEl = node.querySelector(
                            'a.' + TITLE_CLASS
                        );
                        if (!titleEl) continue;
                        
                        const title = titleEl.innerText;
                        const videoUrl = titleEl.getAttribute('href');
                        
                        const channelQuery =
                            'a[href*="/channel/"], ' +
                            'a[href*="/user/"], a[href*="@"]';
                        const channelEl = node.querySelector(channelQuery);
                        const channelName = channelEl
                            ? channelEl.innerText
                            : "Unknown";
                        
                        let timeStr = "";
                        const detailsBtn = node.querySelector('.WFTFcf');
                        if (detailsBtn && detailsBtn.parentElement) {
                            const detailsParent = detailsBtn.parentElement;
                            const timeContainerText = detailsParent.innerText;
                            const match = timeContainerText.match(
                                /(\\d{1,2}:\\d{2})/
                            );
                            if (match) {
                                timeStr = match[1];
                            }
                        }
                        
                        const dateText = currentDate;

                        results.push({
                            type: 'item',
                            date: dateText,
                            title: title,
                            video_url: videoUrl,
                            channel_name: channelName,
                            full_text: node.innerText,
                            time_str: timeStr
                        });
                        
                    } catch (e) {
                        console.error(e);
                    }
                }
                return results;
            }
            """
        )

        items = []
        for data in scraped_data:
            if data["type"] != "item":
                continue

            # データの整形とタイムスタンプ解析
            try:
                video_url = data.get("video_url")
                if not video_url:
                    continue

                video_id = _extract_video_id(video_url)
                if not video_id:
                    continue

                # 日時の構築
                date_str = data.get("date", "")

                # JSで抽出した時刻を優先使用
                time_str = data.get("time_str", "")

                if not time_str:
                    # Fallback: full_textから抽出
                    full_text = data.get("full_text", "")
                    time_match = re.search(r"(\d{1,2}:\d{2})", full_text)
                    time_str = time_match.group(1) if time_match else "00:00"

                # 日付文字列と時刻を結合してパース
                watched_at = self._parse_relative_datetime(date_str, time_str)

                if not watched_at:
                    # パース失敗時はスキップ
                    continue

                # タイムスタンプフィルタ
                if watched_at < after_timestamp:
                    continue

                items.append(
                    {
                        "video_id": video_id,
                        "title": data.get("title"),
                        "channel_name": data.get("channel_name"),
                        "watched_at": watched_at,
                        "video_url": video_url,
                    }
                )

            except Exception as e:
                logger.warning("Failed to process scraped item: %s", e)
                continue

        return items

    def _parse_relative_datetime(self, date_str: str, time_str: str) -> datetime | None:
        """相対日付("今日", "昨日")やMyActivityの日付形式をパースしてdatetimeを返す。"""
        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)
        target_date = None

        date_str = date_str.strip()

        # 相対日付の処理
        if "今日" in date_str or "Today" in date_str:
            target_date = now.date()
        elif "昨日" in date_str or "Yesterday" in date_str:
            target_date = (now - timedelta(days=1)).date()
        else:
            # 一般的な日付形式のパース
            # 2025/01/26, 1月26日, Jan 26, 2025 等
            # 現在の年を補完する必要がある場合(年がない場合)を考慮

            # 日本語形式: "1月26日" -> 現在の年と仮定 (ただし未来になるなら去年)
            # "2024年12月31日" -> そのまま

            # 簡易実装: 主要な形式をトライ
            parsed_date = None
            formats = [
                "%Y年%m月%d日",
                "%m月%d日",
                "%Y/%m/%d",
                "%b %d, %Y",  # Jan 26, 2025
                "%b %d",  # Jan 26
            ]

            for fmt in formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    # 年がない形式の補完
                    if "%Y" not in fmt:
                        dt = dt.replace(year=now.year)
                        if dt.date() > now.date():
                            dt = dt.replace(year=now.year - 1)
                    parsed_date = dt.date()
                    break
                except ValueError:
                    continue

            target_date = parsed_date

        if not target_date:
            return None

        # 時刻のパース
        try:
            h, m = map(int, time_str.split(":"))
            local_dt = datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                h,
                m,
                0,
                tzinfo=tz,
            )
            return local_dt.astimezone(timezone.utc)
        except ValueError:
            return None
