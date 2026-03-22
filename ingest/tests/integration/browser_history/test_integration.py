from io import BytesIO
from unittest.mock import patch

import pandas as pd

from ingest.browser_history.pipeline import run_browser_history_pipeline
from ingest.browser_history.schema import BrowserHistoryPayload
from ingest.browser_history.storage import BrowserHistoryStorage


def _payload(url: str, visit_time: str, visit_id: str) -> BrowserHistoryPayload:
    return BrowserHistoryPayload.model_validate(
        {
            "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
            "source_device": "device-1",
            "browser": "edge",
            "profile": "Default",
            "synced_at": "2026-03-22T12:00:00Z",
            "items": [
                {
                    "url": url,
                    "visit_time": visit_time,
                    "visit_id": visit_id,
                }
            ],
        }
    )


class _MemoryS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):  # noqa: N803
        if isinstance(Body, str):
            body = Body.encode("utf-8")
        else:
            body = Body
        self.objects[Key] = body
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_object(self, *, Bucket, Key):  # noqa: N803
        return {"Body": BytesIO(self.objects[Key])}

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        store = self.objects

        class _Paginator:
            def paginate(self, *, Bucket, Prefix):  # noqa: N803
                keys = [{"Key": key} for key in store if key.startswith(Prefix)]
                yield {"Contents": keys}

        return _Paginator()


def test_integration_saves_raw_events_and_state():
    memory_s3 = _MemoryS3()

    with patch_storage_client(memory_s3):
        storage = BrowserHistoryStorage(
            endpoint_url="http://test-endpoint",
            access_key_id="test-key",
            secret_access_key="test-secret",
            bucket_name="test-bucket",
        )
        run_browser_history_pipeline(
            _payload("https://example.com", "2026-03-22T08:31:12Z", "v1"),
            storage,
        )

        keys = list(memory_s3.objects)
        assert any(key.startswith("raw/browser_history/edge/") for key in keys)
        assert any(
            key.startswith("events/browser_history/visits/year=2026/month=03/")
            for key in keys
        )
        assert "state/browser_history/device-1/edge/Default.json" in keys


def test_integration_compaction_deduplicates_duplicate_event_ids():
    memory_s3 = _MemoryS3()

    with patch_storage_client(memory_s3):
        storage = BrowserHistoryStorage(
            endpoint_url="http://test-endpoint",
            access_key_id="test-key",
            secret_access_key="test-secret",
            bucket_name="test-bucket",
        )
        payload = _payload("https://example.com", "2026-03-22T08:31:12Z", "v1")
        run_browser_history_pipeline(payload, storage)
        run_browser_history_pipeline(payload, storage)

        key = storage.compact_month(year=2026, month=3)

        assert key == (
            "compacted/events/browser_history/visits/year=2026/month=03/data.parquet"
        )
        df = pd.read_parquet(BytesIO(memory_s3.objects[key]))
        assert len(df) == 1


class patch_storage_client:
    def __init__(self, client):
        self.client = client
        self.patcher = None

    def __enter__(self):
        self.patcher = patch(
            "ingest.browser_history.storage.boto3.client",
            return_value=self.client,
        )
        self.patcher.start()
        return self.client

    def __exit__(self, exc_type, exc, tb):
        if self.patcher is not None:
            self.patcher.stop()
