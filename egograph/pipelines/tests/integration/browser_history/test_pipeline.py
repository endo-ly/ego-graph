"""Browser History ingest のインテグレーションテスト。

MemoryS3 モックを使用し、payload → raw/events/state 保存を検証する。
"""

from io import BytesIO
from unittest.mock import patch

import pandas as pd

from pipelines.sources.browser_history.pipeline import run_browser_history_pipeline
from pipelines.sources.browser_history.schema import BrowserHistoryPayload
from pipelines.sources.browser_history.storage import BrowserHistoryStorage


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


class patch_storage_client:
    def __init__(self, client):
        self.client = client
        self.patcher = None

    def __enter__(self):
        self.patcher = patch(
            "pipelines.sources.browser_history.storage.boto3.client",
            return_value=self.client,
        )
        self.patcher.start()
        return self.client

    def __exit__(self, exc_type, exc, tb):
        if self.patcher is not None:
            self.patcher.stop()


def _make_storage(memory_s3: _MemoryS3) -> BrowserHistoryStorage:
    return BrowserHistoryStorage(
        endpoint_url="http://test-endpoint",
        access_key_id="test-key",
        secret_access_key="test-secret",
        bucket_name="test-bucket",
    )


def test_ingest_saves_raw_events_and_state():
    """Ingest が raw JSON, events Parquet, state を S3 に保存する。"""
    memory_s3 = _MemoryS3()

    with patch_storage_client(memory_s3):
        storage = _make_storage(memory_s3)
        run_browser_history_pipeline(
            _payload("https://example.com", "2026-03-22T08:31:12Z", "v1"),
            storage,
        )

        keys = list(memory_s3.objects)
        assert any(key.startswith("raw/browser_history/edge/") for key in keys), (
            "raw data not found"
        )
        assert any(
            key.startswith("events/browser_history/page_views/year=2026/month=03/")
            for key in keys
        ), "events parquet not found"
        assert "state/browser_history/device-1/edge/Default.json" in keys, (
            "state not found"
        )


def test_ingest_no_data_saves_state_only():
    """items が空の場合、state のみ保存する（raw/events は保存しない）。"""
    memory_s3 = _MemoryS3()

    with patch_storage_client(memory_s3):
        storage = _make_storage(memory_s3)
        payload = BrowserHistoryPayload.model_validate(
            {
                "sync_id": "00000000-0000-0000-0000-000000000001",
                "source_device": "device-1",
                "browser": "edge",
                "profile": "Default",
                "synced_at": "2026-03-22T12:00:00Z",
                "items": [],
            }
        )
        run_browser_history_pipeline(payload, storage)

        keys = list(memory_s3.objects)
        # state は保存される
        assert "state/browser_history/device-1/edge/Default.json" in keys
        # raw/events は保存されない
        assert not any(key.startswith("raw/") for key in keys), (
            "raw data should not be saved"
        )
        assert not any(key.startswith("events/") for key in keys), (
            "events should not be saved"
        )


def test_compact_deduplicates_duplicate_event_ids():
    """Compaction が同一 visit_id のレコードを重複排除する。"""
    memory_s3 = _MemoryS3()

    with patch_storage_client(memory_s3):
        storage = _make_storage(memory_s3)
        payload = _payload("https://example.com", "2026-03-22T08:31:12Z", "v1")
        run_browser_history_pipeline(payload, storage)
        run_browser_history_pipeline(payload, storage)

        key = storage.compact_month(year=2026, month=3)

        assert key == (
            "compacted/events/browser_history/page_views/year=2026/month=03/data.parquet"
        )
        df = pd.read_parquet(BytesIO(memory_s3.objects[key]))
        assert len(df) == 1, f"Expected 1 deduplicated row, got {len(df)}"


def test_compact_skips_empty_month():
    """データがない月の compaction は None を返す。"""
    memory_s3 = _MemoryS3()

    with patch_storage_client(memory_s3):
        storage = _make_storage(memory_s3)

        key = storage.compact_month(year=2026, month=3)

        assert key is None


def test_incremental_fetch_uses_state():
    """2回目の ingest は state を更新する。"""
    memory_s3 = _MemoryS3()

    with patch_storage_client(memory_s3):
        storage = _make_storage(memory_s3)

        # 1回目
        payload1 = _payload("https://example.com/a", "2026-03-22T08:31:12Z", "v1")
        run_browser_history_pipeline(payload1, storage)

        state_key = "state/browser_history/device-1/edge/Default.json"
        assert state_key in memory_s3.objects

        # 2回目
        payload2 = _payload("https://example.com/b", "2026-03-22T09:00:00Z", "v2")
        run_browser_history_pipeline(payload2, storage)

        # state が更新されている
        import json

        state = json.loads(memory_s3.objects[state_key])
        assert state["sync_id"] == "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf"
        assert state["last_accepted_count"] == 1
