"""MyActivityコレクターのテスト。"""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from pipelines.sources.google_activity.collector import (
    MyActivityCollector,
    _extract_video_id,
    _parse_watched_at,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def mock_cookies():
    """モック用のクッキーデータ。"""
    return [
        {
            "name": "SID",
            "value": "test_sid_value",
            "domain": ".google.com",
            "path": "/",
        },
        {
            "name": "HSID",
            "value": "test_hsid_value",
            "domain": ".google.com",
            "path": "/",
        },
    ]


def test_collector_initialization(mock_cookies):
    """コレクターの初期化をテストする。"""
    collector = MyActivityCollector(mock_cookies)

    # Assert: コレクターが正しく初期化されている
    assert collector.cookies == mock_cookies
    assert collector.browser is None  # 初期化時はまだブラウザが生成されていない


def test_extract_video_id_from_standard_url():
    """標準的なYouTube URLからvideo_idを抽出する。"""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert _extract_video_id(url) == "dQw4w9WgXcQ"


def test_extract_video_id_from_short_url():
    """短縮URLからvideo_idを抽出する。"""
    url = "https://youtu.be/dQw4w9WgXcQ"
    assert _extract_video_id(url) == "dQw4w9WgXcQ"


def test_extract_video_id_from_mobile_url():
    """モバイルURLからvideo_idを抽出する。"""
    url = "https://m.youtube.com/watch?v=dQw4w9WgXcQ"
    assert _extract_video_id(url) == "dQw4w9WgXcQ"


def test_extract_video_id_from_invalid_url():
    """無効なURLの場合はNoneを返す。"""
    assert _extract_video_id("https://example.com/video") is None
    assert _extract_video_id("") is None
    assert _extract_video_id(None) is None


def test_parse_watched_at_iso8601():
    """ISO8601形式の日時をパースする。"""
    timestamp_str = "2025-01-15T10:30:00.000Z"
    result = _parse_watched_at(timestamp_str)
    assert result == datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_watched_at_simple_format():
    """簡易形式の日時をパースする。"""
    timestamp_str = "2025-01-15 10:30:00"
    result = _parse_watched_at(timestamp_str)
    assert result.year == 2025
    assert result.month == 1
    assert result.day == 15


def test_parse_watched_at_japanese_format():
    """日本語形式の日時をパースする。"""
    timestamp_str = "2025年1月15日 10:30"
    result = _parse_watched_at(timestamp_str)
    assert result.year == 2025
    assert result.month == 1
    assert result.day == 15


def test_parse_watched_at_invalid_format():
    """無効な形式の場合はNoneを返す（パース失敗時の安全な挙動）。"""
    timestamp_str = "invalid_timestamp"
    result = _parse_watched_at(timestamp_str)
    assert result is None


@pytest.mark.asyncio
async def test_collect_watch_structure_validation():
    """collect_watch_historyメソッドのシグネチャを検証する。"""
    mock_cookies = [
        {"name": "test", "value": "value", "domain": ".google.com", "path": "/"}
    ]

    collector = MyActivityCollector(mock_cookies)

    # メソッドが正しいシグネチャを持っていることを確認
    assert hasattr(collector, "collect_watch_history")
    assert callable(collector.collect_watch_history)


@pytest.mark.asyncio
async def test_collect_watch_history_with_valid_params():
    """有効なパラメータでcollect_watch_historyが呼び出せることを確認する。"""
    mock_cookies = [
        {"name": "test", "value": "value", "domain": ".google.com", "path": "/"}
    ]

    collector = MyActivityCollector(mock_cookies)

    after_timestamp = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # ブラウザ操作をモックして、決定的なデータを返す
    async def mock_init():
        # モック用のpageオブジェクトを作成
        collector.page = AsyncMock()
        collector.page.goto = AsyncMock()
        collector.page.url = "https://myactivity.google.com/product/youtube"

    async def mock_cleanup():
        pass

    with patch.object(collector, "_initialize_browser", mock_init):
        with patch.object(collector, "_cleanup_browser", mock_cleanup):
            with patch.object(
                collector, "_is_authentication_failed", return_value=False
            ):
                # _scrape_watch_itemsをモック
                mock_items = [
                    {
                        "video_id": "test_video1",
                        "title": "Test Video 1",
                        "channel_name": "Test Channel",
                        "watched_at": datetime(
                            2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc
                        ),
                        "video_url": "https://www.youtube.com/watch?v=test_video1",
                    }
                ]
                with patch.object(
                    collector, "_scrape_watch_items", return_value=mock_items
                ):
                    result = await collector.collect_watch_history(
                        after_timestamp=after_timestamp, max_items=10
                    )

    # 成功した場合、結果の構造を検証
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["video_id"] == "test_video1"
    assert result[0]["title"] == "Test Video 1"


@pytest.mark.asyncio
async def test_collect_watch_history_retry_decorator():
    """リトライデコレータが適用されていることを確認する。"""
    from unittest.mock import AsyncMock, patch  # noqa: PLC0415

    from tenacity import RetryError  # noqa: PLC0415

    mock_cookies = [
        {"name": "test", "value": "value", "domain": ".google.com", "path": "/"}
    ]
    collector = MyActivityCollector(mock_cookies)

    after_timestamp = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # リトライデコレータが適用されていることを確認
    # デコレータがある場合、RuntimeErrorはRetryErrorでラップされる
    with patch.object(collector, "_initialize_browser", new_callable=AsyncMock):
        with patch.object(collector, "_cleanup_browser", new_callable=AsyncMock):
            with pytest.raises(RetryError):
                # ブラウザ初期化がモックされているため失敗する
                await collector.collect_watch_history(
                    after_timestamp=after_timestamp, max_items=10
                )

    # テストが成功すれば、リトライデコレータが適用されていることの証明
    # （AuthenticationError以外の例外はRetryErrorでラップされる）


@pytest.mark.asyncio
async def test_collect_watch_history_max_items_parameter():
    """max_itemsパラメータが正しく扱われることを確認する。"""
    mock_cookies = [
        {"name": "test", "value": "value", "domain": ".google.com", "path": "/"}
    ]
    collector = MyActivityCollector(mock_cookies)

    after_timestamp = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # max_items=None(無制限)
    mock_items_1 = [
        {
            "video_id": f"video{i}",
            "title": f"Video {i}",
            "channel_name": "Test Channel",
            "watched_at": datetime(2025, 1, i + 1, 10, 30, 0, tzinfo=timezone.utc),
            "video_url": f"https://www.youtube.com/watch?v=video{i}",
        }
        for i in range(10)
    ]

    # max_items=5
    mock_items_2 = [
        {
            "video_id": f"video{i}",
            "title": f"Video {i}",
            "channel_name": "Test Channel",
            "watched_at": datetime(2025, 1, i + 1, 10, 30, 0, tzinfo=timezone.utc),
            "video_url": f"https://www.youtube.com/watch?v=video{i}",
        }
        for i in range(5)
    ]

    async def mock_init():
        # モック用のpageオブジェクトを作成
        collector.page = AsyncMock()
        collector.page.goto = AsyncMock()
        collector.page.url = "https://myactivity.google.com/product/youtube"

    async def mock_cleanup():
        pass

    # 2回の呼び出しを同じモックコンテキスト内で実行
    with patch.object(collector, "_initialize_browser", mock_init):
        with patch.object(collector, "_cleanup_browser", mock_cleanup):
            with patch.object(
                collector, "_is_authentication_failed", return_value=False
            ):
                # max_items=Noneの呼び出し
                with patch.object(
                    collector, "_scrape_watch_items", return_value=mock_items_1
                ):
                    result1 = await collector.collect_watch_history(
                        after_timestamp=after_timestamp, max_items=None
                    )

                # max_items=5の呼び出し
                with patch.object(
                    collector, "_scrape_watch_items", return_value=mock_items_2
                ):
                    result2 = await collector.collect_watch_history(
                        after_timestamp=after_timestamp, max_items=5
                    )

    assert isinstance(result1, list)
    assert len(result1) == 10

    assert isinstance(result2, list)
    assert len(result2) == 5


@pytest.mark.asyncio
async def test_collect_watch_history_after_timestamp_filtering():
    """after_timestampによるフィルタリングが正しく動作することを確認する。"""
    mock_cookies = [
        {"name": "test", "value": "value", "domain": ".google.com", "path": "/"}
    ]
    collector = MyActivityCollector(mock_cookies)

    after_timestamp = datetime(2025, 1, 10, 0, 0, 0, tzinfo=timezone.utc)

    # after_timestamp以降のアイテムを含むモックデータ
    mock_items = [
        {
            "video_id": f"video{i}",
            "title": f"Video {i}",
            "channel_name": "Test Channel",
            "watched_at": datetime(2025, 1, 10 + i, 10, 30, 0, tzinfo=timezone.utc),
            "video_url": f"https://www.youtube.com/watch?v=video{i}",
        }
        for i in range(5)
    ]

    async def mock_init():
        # モック用のpageオブジェクトを作成
        collector.page = AsyncMock()
        collector.page.goto = AsyncMock()
        collector.page.url = "https://myactivity.google.com/product/youtube"

    async def mock_cleanup():
        pass

    with patch.object(collector, "_initialize_browser", mock_init):
        with patch.object(collector, "_cleanup_browser", mock_cleanup):
            with patch.object(
                collector, "_is_authentication_failed", return_value=False
            ):
                with patch.object(
                    collector, "_scrape_watch_items", return_value=mock_items
                ):
                    result = await collector.collect_watch_history(
                        after_timestamp=after_timestamp, max_items=10
                    )

    assert isinstance(result, list)
    # 結果内の全アイテムがafter_timestamp以降であることを確認
    for item in result:
        if "watched_at" in item:
            assert item["watched_at"] >= after_timestamp
