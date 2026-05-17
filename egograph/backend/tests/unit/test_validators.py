"""validators.to_utc_range のテスト。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.validators import to_utc_range


class TestToUtcRange:
    """to_utc_range のテスト。"""

    def test_utc_zone(self):
        """UTC タイムゾーンでの日付変換。"""
        start, end = to_utc_range(date(2026, 5, 17), date(2026, 5, 17), ZoneInfo("UTC"))

        assert start == datetime(2026, 5, 17, 0, 0, 0)
        assert start.tzinfo is None
        assert end == datetime(2026, 5, 18, 0, 0, 0)
        assert end.tzinfo is None

    def test_tokyo_zone_single_day(self):
        """Asia/Tokyo で1日の範囲を UTC に変換。"""
        start, end = to_utc_range(
            date(2026, 5, 17), date(2026, 5, 17), ZoneInfo("Asia/Tokyo")
        )

        assert start == datetime(2026, 5, 16, 15, 0, 0)
        assert start.tzinfo is None
        assert end == datetime(2026, 5, 17, 15, 0, 0)
        assert end.tzinfo is None

    def test_tokyo_zone_multi_day(self):
        """Asia/Tokyo で複数日の範囲を UTC に変換。"""
        start, end = to_utc_range(
            date(2026, 5, 1), date(2026, 5, 3), ZoneInfo("Asia/Tokyo")
        )

        assert start == datetime(2026, 4, 30, 15, 0, 0)
        assert end == datetime(2026, 5, 3, 15, 0, 0)

    def test_tokyo_midnight_boundary(self):
        """JST 23:59 のデータが正しく含まれることを確認。

        JST 2026-05-17 23:59 = UTC 2026-05-17 14:59
        utc_end は UTC 2026-05-18 15:00 なので含まれる。
        """
        _, end = to_utc_range(
            date(2026, 5, 17), date(2026, 5, 17), ZoneInfo("Asia/Tokyo")
        )

        jst_midnight_event = datetime(2026, 5, 17, 14, 59, 0)
        assert jst_midnight_event < end

    def test_nyc_zone(self):
        """America/New_York での日付変換。"""
        start, end = to_utc_range(
            date(2026, 1, 15), date(2026, 1, 15), ZoneInfo("America/New_York")
        )

        # EST (UTC-5): 2026-01-15 00:00 EST = 2026-01-15 05:00 UTC
        assert start == datetime(2026, 1, 15, 5, 0, 0)
        assert end == datetime(2026, 1, 16, 5, 0, 0)

    def test_returns_naive_datetime(self):
        """返り値が naive datetime（tzinfo=None）であること。"""
        start, end = to_utc_range(date(2024, 1, 1), date(2024, 1, 1), ZoneInfo("UTC"))
        assert start.tzinfo is None
        assert end.tzinfo is None
