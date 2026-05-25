"""Browser History Queries層のテスト。"""

from datetime import date, timezone
from unittest.mock import patch

from pydantic import SecretStr

from backend.config import R2Config
from backend.infrastructure.database import (
    QueryParams,
    get_page_views,
    get_top_domains,
)
from backend.validators import to_utc_range


def _make_r2_config(bucket_name: str = "test-bucket") -> R2Config:
    return R2Config.model_construct(
        endpoint_url="https://test.r2.cloudflarestorage.com",
        access_key_id="test_key",
        secret_access_key=SecretStr("test_secret"),
        bucket_name=bucket_name,
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
        local_parquet_root=None,
    )


def _bqp(**overrides):
    """テスト用 QueryParams ファクトリ。"""
    defaults: dict = dict(
        r2_config=_make_r2_config(),
        tz_name="UTC",
    )
    defaults.update(overrides)
    defaults.pop("bucket", None)
    defaults.pop("events_path", None)
    defaults.pop("master_path", None)
    sd = defaults.pop("start_date")
    ed = defaults.pop("end_date")
    utc_start, utc_end = to_utc_range(sd, ed, timezone.utc)
    return QueryParams(
        start_date=sd,
        end_date=ed,
        utc_start=utc_start,
        utc_end=utc_end,
        **defaults,
    )


class TestGetPageViews:
    """get_page_views のテスト。"""

    def test_returns_page_views_in_descending_order(
        self,
        browser_history_with_sample_data,
    ):
        """page view一覧を started_at_utc 降順で返す。"""
        parquet_path = browser_history_with_sample_data.test_page_views_parquet_path

        with patch(
            "backend.infrastructure.database.browser_history_queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            params = _bqp(
                conn=browser_history_with_sample_data,
                start_date=date(2026, 3, 20),
                end_date=date(2026, 3, 22),
            )

            result = get_page_views(params, limit=3)

        assert [row["page_view_id"] for row in result] == ["pv_5", "pv_4", "pv_3"]

    def test_filters_by_browser_and_profile(self, browser_history_with_sample_data):
        """browser / profile で絞り込める。"""
        parquet_path = browser_history_with_sample_data.test_page_views_parquet_path

        with patch(
            "backend.infrastructure.database.browser_history_queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            params = _bqp(
                conn=browser_history_with_sample_data,
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
            "backend.infrastructure.database.browser_history_queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            params = _bqp(
                conn=browser_history_with_sample_data,
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
            "backend.infrastructure.database.browser_history_queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            params = _bqp(
                conn=browser_history_with_sample_data,
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
