"""YouTube固有の設定のテスト。"""

from dataclasses import FrozenInstanceError

import pytest

from pipelines.sources.google_activity.config import (
    MAX_RETRIES,
    MYACTIVITY_URL,
    RETRY_BACKOFF_FACTOR,
    SCROLL_DELAY_MAX,
    SCROLL_DELAY_MIN,
    YOUTUBE_API_BATCH_SIZE,
    AccountConfig,
)


class TestConstants:
    """設定定数のテスト。"""

    def test_retry_settings(self):
        """リトライ設定が適切な値であることを確認。"""
        assert MAX_RETRIES == 3
        assert RETRY_BACKOFF_FACTOR == 2

    def test_scroll_delay_settings(self):
        """スクロール遅延設定が適切な範囲であることを確認。"""
        assert SCROLL_DELAY_MIN == 2
        assert SCROLL_DELAY_MAX == 5
        assert SCROLL_DELAY_MIN < SCROLL_DELAY_MAX

    def test_youtube_api_settings(self):
        """YouTube API設定が適切な値であることを確認。"""
        assert YOUTUBE_API_BATCH_SIZE == 50  # API制限
        assert MYACTIVITY_URL == "https://myactivity.google.com/product/youtube"


class TestAccountConfig:
    """AccountConfigデータクラスのテスト。"""

    def test_account_config_creation(self):
        """AccountConfigが正常に作成できることを確認。"""
        config = AccountConfig(
            account_id="account1",
            cookies={"cookie1": "value1"},
            youtube_api_key="test_key",
        )

        assert config.account_id == "account1"
        assert config.cookies == {"cookie1": "value1"}
        assert config.youtube_api_key == "test_key"

    def test_account_config_is_frozen(self):
        """AccountConfigがfrozenであることを確認（イミュータブル）。"""
        config = AccountConfig(
            account_id="account1",
            cookies={},
            youtube_api_key="test_key",
        )

        with pytest.raises(FrozenInstanceError):
            config.account_id = "account2"  # type: ignore

    def test_account_config_required_fields(self):
        """必須フィールドが欠けていると作成できないことを確認。"""
        with pytest.raises(TypeError):
            AccountConfig(account_id="account1")  # type: ignore

    def test_account_config_with_empty_cookies(self):
        """空のcookiesでも作成できることを確認。"""
        config = AccountConfig(
            account_id="account1",
            cookies={},
            youtube_api_key="test_key",
        )

        assert config.cookies == {}
