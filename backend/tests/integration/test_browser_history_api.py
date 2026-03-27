from datetime import datetime
from unittest.mock import ANY, patch

from backend.usecases.browser_history import BrowserHistoryUseCaseError
from ingest.browser_history.pipeline import BrowserHistoryPipelineResult


def _request_payload():
    return {
        "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
        "source_device": "home-windows-pc",
        "browser": "edge",
        "profile": "Default",
        "synced_at": "2026-03-22T12:00:00Z",
        "items": [
            {
                "url": "https://example.com",
                "title": "Example",
                "visit_time": "2026-03-22T08:31:12Z",
                "visit_id": "12345",
            }
        ],
    }


class TestBrowserHistoryApi:
    def test_valid_request_returns_200(self, test_client):
        expected = BrowserHistoryPipelineResult(
            sync_id="2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            accepted=1,
            raw_saved=True,
            events_saved=True,
            received_at=datetime.fromisoformat("2026-03-22T12:00:01+00:00"),
            compaction_targets=((2026, 3),),
        )

        with (
            patch(
                "backend.api.browser_history.ingest_browser_history",
                return_value=expected,
            ),
            patch(
                "backend.api.browser_history._trigger_browser_history_compaction"
            ) as mock_trigger,
        ):
            response = test_client.post(
                "/v1/ingest/browser-history",
                json=_request_payload(),
                headers={"X-API-Key": "test-backend-key"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            "accepted": 1,
            "raw_saved": True,
            "events_saved": True,
            "received_at": "2026-03-22T12:00:01Z",
        }
        mock_trigger.assert_called_once_with(ANY, ((2026, 3),))

    def test_invalid_api_key_returns_401(self, test_client):
        response = test_client.post(
            "/v1/ingest/browser-history",
            json=_request_payload(),
        )

        assert response.status_code == 401

    def test_invalid_payload_returns_400(self, test_client):
        payload = _request_payload()
        payload["profile"] = ""

        response = test_client.post(
            "/v1/ingest/browser-history",
            json=payload,
            headers={"X-API-Key": "test-backend-key"},
        )

        assert response.status_code == 400

    def test_ingest_failure_returns_500(self, test_client):
        with patch(
            "backend.api.browser_history.ingest_browser_history",
            side_effect=BrowserHistoryUseCaseError("storage failed"),
        ):
            response = test_client.post(
                "/v1/ingest/browser-history",
                json=_request_payload(),
                headers={"X-API-Key": "test-backend-key"},
            )

        assert response.status_code == 500

    def test_response_contains_required_fields(self, test_client):
        expected = BrowserHistoryPipelineResult(
            sync_id="2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            accepted=1,
            raw_saved=True,
            events_saved=True,
            received_at=datetime.fromisoformat("2026-03-22T12:00:01+00:00"),
        )

        with patch(
            "backend.api.browser_history.ingest_browser_history",
            return_value=expected,
        ):
            response = test_client.post(
                "/v1/ingest/browser-history",
                json=_request_payload(),
                headers={"X-API-Key": "test-backend-key"},
            )

        data = response.json()
        assert set(data) == {
            "sync_id",
            "accepted",
            "raw_saved",
            "events_saved",
            "received_at",
        }

    def test_empty_compaction_targets_skip_background_compaction(self, test_client):
        expected = BrowserHistoryPipelineResult(
            sync_id="2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            accepted=1,
            raw_saved=True,
            events_saved=False,
            received_at=datetime.fromisoformat("2026-03-22T12:00:01+00:00"),
            compaction_targets=(),
        )

        with (
            patch(
                "backend.api.browser_history.ingest_browser_history",
                return_value=expected,
            ),
            patch(
                "backend.api.browser_history._trigger_browser_history_compaction"
            ) as mock_trigger,
        ):
            response = test_client.post(
                "/v1/ingest/browser-history",
                json=_request_payload(),
                headers={"X-API-Key": "test-backend-key"},
            )

        assert response.status_code == 200
        mock_trigger.assert_not_called()

    def test_compaction_failure_does_not_fail_ingest_response(self, test_client):
        expected = BrowserHistoryPipelineResult(
            sync_id="2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            accepted=1,
            raw_saved=True,
            events_saved=True,
            received_at=datetime.fromisoformat("2026-03-22T12:00:01+00:00"),
            compaction_targets=((2026, 3),),
        )

        with (
            patch(
                "backend.api.browser_history.ingest_browser_history",
                return_value=expected,
            ),
            patch(
                "backend.api.browser_history.compact_ingested_browser_history",
                side_effect=RuntimeError("boom"),
            ),
        ):
            response = test_client.post(
                "/v1/ingest/browser-history",
                json=_request_payload(),
                headers={"X-API-Key": "test-backend-key"},
            )

        assert response.status_code == 200
