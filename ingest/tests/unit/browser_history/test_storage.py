import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from ingest.browser_history.storage import BrowserHistoryStorage


class TestBrowserHistoryStorage:
    def setup_method(self):
        self.mock_boto3 = patch("ingest.browser_history.storage.boto3").start()
        self.mock_s3 = MagicMock()
        self.mock_boto3.client.return_value = self.mock_s3
        self.storage = BrowserHistoryStorage(
            endpoint_url="http://test-endpoint",
            access_key_id="test-key",
            secret_access_key="test-secret",
            bucket_name="test-bucket",
        )

    def teardown_method(self):
        patch.stopall()

    def test_save_raw_json_uses_expected_key_format(self):
        key = self.storage.save_raw_json(
            {"items": [1]},
            browser="edge",
        )

        assert key is not None
        assert key.startswith("raw/browser_history/edge/")
        assert key.endswith(".json")

    def test_save_parquet_uses_expected_key_format(self):
        with patch(
            "ingest.browser_history.storage.pd.DataFrame.to_parquet"
        ) as _mock_to_parquet:
            key = self.storage.save_parquet(
                [{"event_id": "e1", "visited_at_utc": "2026-03-22T08:31:12Z"}],
                year=2026,
                month=3,
            )

        assert key is not None
        assert key.startswith("events/browser_history/visits/year=2026/month=03/")
        assert key.endswith(".parquet")

    def test_build_state_key_uses_source_browser_profile_granularity(self):
        key = self.storage.build_state_key("home pc", "edge", "Profile 1")

        assert key == "state/browser_history/home%20pc/edge/Profile%201.json"

    def test_get_state_returns_none_on_missing_key(self):
        self.mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}},
            "GetObject",
        )

        state = self.storage.get_state(
            source_device="device-1",
            browser="edge",
            profile="Default",
        )

        assert state is None

    def test_save_state_writes_json(self):
        self.storage.save_state(
            {"sync_id": "abc"},
            source_device="device-1",
            browser="edge",
            profile="Default",
        )

        call_args = self.mock_s3.put_object.call_args.kwargs
        assert call_args["Key"] == "state/browser_history/device-1/edge/Default.json"
        assert json.loads(call_args["Body"]) == {"sync_id": "abc"}

    def test_compact_month_saves_fixed_compacted_key(self):
        with patch(
            "ingest.browser_history.storage.read_parquet_records_from_prefix",
            return_value=[
                {"event_id": "e1", "ingested_at_utc": "2026-03-22T12:00:00Z"}
            ],
        ), patch(
            "ingest.browser_history.storage.dataframe_to_parquet_bytes",
            return_value=b"x",
        ):
            key = self.storage.compact_month(year=2026, month=3)

        assert key == (
            "compacted/events/browser_history/visits/year=2026/month=03/data.parquet"
        )
