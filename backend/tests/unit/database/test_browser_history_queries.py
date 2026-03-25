"""Browser History Queries層のテスト。"""

from datetime import date
from unittest.mock import patch

from backend.infrastructure.database import (
    BrowserHistoryQueryParams,
    get_page_views,
    get_top_domains,
)
from backend.infrastructure.database.browser_history_queries import (
    _generate_browser_history_partition_paths,
)


class TestGenerateBrowserHistoryPartitionPaths:
    """Browser Historyパーティションパス生成のテスト。"""

    def test_generates_single_month_path(self):
        """同月期間のパスを生成する。"""
        paths = _generate_browser_history_partition_paths(
            bucket="test-bucket",
            events_path="events/",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
        )

        assert paths == [
            "s3://test-bucket/events/browser_history/page_views/year=2026/month=03/**/*.parquet"
        ]

    def test_generates_multiple_month_paths(self):
        """複数月期間のパスを生成する。"""
        paths = _generate_browser_history_partition_paths(
            bucket="test-bucket",
            events_path="events/",
            start_date=date(2026, 3, 20),
            end_date=date(2026, 5, 1),
        )

        assert len(paths) == 3
        assert "year=2026/month=03" in paths[0]
        assert "year=2026/month=04" in paths[1]
        assert "year=2026/month=05" in paths[2]


class TestGetPageViews:
    """get_page_views のテスト。"""

    def test_returns_page_views_in_descending_order(
        self,
        browser_history_with_sample_data,
    ):
        """page view一覧を started_at_utc 降順で返す。"""
        parquet_path = browser_history_with_sample_data.test_page_views_parquet_path

        with patch(
            "backend.infrastructure.database.browser_history_queries._generate_browser_history_partition_paths",
            return_value=[parquet_path],
        ):
            params = BrowserHistoryQueryParams(
                conn=browser_history_with_sample_data,
                bucket="test-bucket",
                events_path="events/",
                start_date=date(2026, 3, 20),
                end_date=date(2026, 3, 22),
            )

            result = get_page_views(params, limit=3)

        assert [row["page_view_id"] for row in result] == ["pv_5", "pv_4", "pv_3"]

    def test_filters_by_browser_and_profile(self, browser_history_with_sample_data):
        """browser / profile で絞り込める。"""
        parquet_path = browser_history_with_sample_data.test_page_views_parquet_path

        with patch(
            "backend.infrastructure.database.browser_history_queries._generate_browser_history_partition_paths",
            return_value=[parquet_path],
        ):
            params = BrowserHistoryQueryParams(
                conn=browser_history_with_sample_data,
                bucket="test-bucket",
                events_path="events/",
                start_date=date(2026, 3, 20),
                end_date=date(2026, 3, 22),
            )

            result = get_page_views(
                params,
                browser="edge",
                profile="Default",
                limit=10,
            )

        assert [row["page_view_id"] for row in result] == ["pv_5", "pv_2", "pv_1"]
        assert all(row["browser"] == "edge" for row in result)
        assert all(row["profile"] == "Default" for row in result)


class TestGetTopDomains:
    """get_top_domains のテスト。"""

    def test_aggregates_domain_counts(self, browser_history_with_sample_data):
        """domain ごとの page view 数と unique URL 数を返す。"""
        parquet_path = browser_history_with_sample_data.test_page_views_parquet_path

        with patch(
            "backend.infrastructure.database.browser_history_queries._generate_browser_history_partition_paths",
            return_value=[parquet_path],
        ):
            params = BrowserHistoryQueryParams(
                conn=browser_history_with_sample_data,
                bucket="test-bucket",
                events_path="events/",
                start_date=date(2026, 3, 20),
                end_date=date(2026, 3, 22),
            )

            result = get_top_domains(params, limit=10)

        assert result[0] == {
            "domain": "github.com",
            "page_view_count": 3,
            "unique_urls": 3,
        }
        assert result[1]["domain"] == "docs.python.org"
        assert result[2]["domain"] == "news.ycombinator.com"

    def test_filters_top_domains(self, browser_history_with_sample_data):
        """browser / profile 指定で domain 集計を絞り込める。"""
        parquet_path = browser_history_with_sample_data.test_page_views_parquet_path

        with patch(
            "backend.infrastructure.database.browser_history_queries._generate_browser_history_partition_paths",
            return_value=[parquet_path],
        ):
            params = BrowserHistoryQueryParams(
                conn=browser_history_with_sample_data,
                bucket="test-bucket",
                events_path="events/",
                start_date=date(2026, 3, 20),
                end_date=date(2026, 3, 22),
            )

            result = get_top_domains(
                params,
                browser="edge",
                profile="Default",
                limit=10,
            )

        assert result == [
            {
                "domain": "github.com",
                "page_view_count": 2,
                "unique_urls": 2,
            },
            {
                "domain": "news.ycombinator.com",
                "page_view_count": 1,
                "unique_urls": 1,
            },
        ]
