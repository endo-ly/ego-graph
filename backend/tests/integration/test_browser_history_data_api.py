"""Browser History Data API 統合テスト。"""

from unittest.mock import patch


class TestPageViewsEndpoint:
    """page-views エンドポイントのテスト。"""

    def test_get_page_views_success(self, test_client, mock_db_and_parquet):
        mock_result = [
            {
                "page_view_id": "pv_1",
                "started_at_utc": "2026-03-22T12:00:00Z",
                "ended_at_utc": "2026-03-22T12:00:02Z",
                "url": "https://github.com/owner/repo/pull/79",
                "title": "PR 79",
                "browser": "edge",
                "profile": "Default",
                "transition": "link",
                "visit_span_count": 2,
            }
        ]

        with patch(
            "backend.api.browser_history_data.get_page_views",
            return_value=mock_result,
        ):
            response = test_client.get(
                "/v1/data/browser-history/page-views?start_date=2026-03-20&end_date=2026-03-22&limit=5&browser=edge&profile=Default",
                headers={"X-API-Key": "test-backend-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data[0]["page_view_id"] == "pv_1"
        assert data[0]["browser"] == "edge"

    def test_get_page_views_requires_api_key(self, test_client):
        response = test_client.get(
            "/v1/data/browser-history/page-views?start_date=2026-03-20&end_date=2026-03-22"
        )

        assert response.status_code == 401

    def test_get_page_views_requires_dates(self, test_client):
        response = test_client.get(
            "/v1/data/browser-history/page-views?limit=5",
            headers={"X-API-Key": "test-backend-key"},
        )

        assert response.status_code == 422


class TestTopDomainsEndpoint:
    """top-domains エンドポイントのテスト。"""

    def test_get_top_domains_success(self, test_client, mock_db_and_parquet):
        mock_result = [
            {
                "domain": "github.com",
                "page_view_count": 12,
                "unique_urls": 5,
            }
        ]

        with patch(
            "backend.api.browser_history_data.get_top_domains",
            return_value=mock_result,
        ):
            response = test_client.get(
                "/v1/data/browser-history/top-domains?start_date=2026-03-20&end_date=2026-03-22&limit=5&browser=edge&profile=Default",
                headers={"X-API-Key": "test-backend-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data == mock_result

    def test_get_top_domains_requires_dates(self, test_client):
        response = test_client.get(
            "/v1/data/browser-history/top-domains?limit=5",
            headers={"X-API-Key": "test-backend-key"},
        )

        assert response.status_code == 422
