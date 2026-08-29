"""Google Health Raw replayのテスト。"""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from unittest.mock import patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from pipelines.sources.google_health.replay import replay_google_health_raw
from pipelines.sources.google_health.writer import GoogleHealthWriter


class MemoryS3:
    """Raw/events/compactedを保持するin-memory S3。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.last_modified: dict[str, datetime] = {}
        self._write_count = 0

    def put_object(self, *, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[Key] = Body
        self.last_modified[Key] = datetime(
            2026,
            6,
            1,
            tzinfo=UTC,
        ) + timedelta(seconds=self._write_count)
        self._write_count += 1

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)
        self.last_modified.pop(Key, None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        last_modified = self.last_modified

        class Paginator:
            def __init__(self, objects):
                self.objects = objects

            def paginate(self, *, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": key, "LastModified": last_modified[key]}
                        for key in sorted(self.objects)
                        if key.startswith(Prefix)
                    ]
                }

        return Paginator(self.objects)


def _writer(memory_s3: MemoryS3) -> GoogleHealthWriter:
    with patch(
        "pipelines.sources.google_health.writer.boto3.client",
        return_value=memory_s3,
    ):
        return GoogleHealthWriter(
            endpoint_url="https://r2.example.test",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            raw_path="archive/",
        )


def test_replay_rebuilds_new_datasets_and_is_idempotent():
    """Raw replayが新schemaを作り、同じRawの再実行で重複しない。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-1",
        payload={
            "reconcileResponses": [
                {
                    "dataPoints": [
                        {
                            "dataPointName": "heart-rate-1",
                            "heartRate": {
                                "sampleTime": {"physicalTime": "2026-06-01T01:00:00Z"},
                                "beatsPerMinute": 72,
                            },
                        }
                    ]
                }
            ]
        },
    )

    # Act
    first = replay_google_health_raw(writer, reset_compacted=True)
    second = replay_google_health_raw(writer, reset_compacted=True)

    # Assert
    assert first["raw_count"] == 1
    assert second["raw_count"] == 1
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )
    rows = pd.read_parquet(BytesIO(memory_s3.objects[compacted_key]))
    assert len(rows) == 1
    assert rows.iloc[0]["value"] == 72.0
    assert any("archive/google_health/" in key for key in memory_s3.objects)


def test_replay_replaces_delayed_rollup_values_in_raw_save_order():
    """後日再取得されたdaily rollupが過去値へ加算されず置換される。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    for run_id, value in (("run-old", 8000), ("run-repair", 10000)):
        writer.save_raw(
            connection_id="connection-1",
            data_type="steps",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 2),
            run_id=run_id,
            payload={
                "dailyRollupResponses": [
                    {
                        "rollupDataPoints": [
                            {
                                "civilStartTime": {
                                    "date": {
                                        "year": 2026,
                                        "month": 6,
                                        "day": 1,
                                    }
                                },
                                "steps": {"countSum": value},
                            }
                        ]
                    }
                ]
            },
        )

    # Act
    replay_google_health_raw(writer, reset_compacted=True)

    # Assert
    daily_path = (
        "compacted/events/google_health/daily_metrics/year=2026/month=06/data.parquet"
    )
    records_path = (
        "compacted/events/google_health/records/year=2026/month=06/data.parquet"
    )
    daily = pd.read_parquet(BytesIO(memory_s3.objects[daily_path]))
    records = pd.read_parquet(BytesIO(memory_s3.objects[records_path]))
    assert len(daily) == 1
    assert daily.iloc[0]["value"] == 10000.0
    assert len(records) == 1
    assert '"countSum":10000' in records.iloc[0]["payload_json"]


def test_replay_validates_all_raw_before_resetting_compacted():
    """不正Rawで全面再構築しても既存compactedを先に削除しない。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-valid",
        payload={
            "reconcileResponses": [
                {
                    "dataPoints": [
                        {
                            "heartRate": {
                                "sampleTime": {"physicalTime": "2026-06-01T01:00:00Z"},
                                "beatsPerMinute": 72,
                            }
                        }
                    ]
                }
            ]
        },
    )
    replay_google_health_raw(writer, reset_compacted=True)
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )

    writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-invalid",
        payload={
            "reconcileResponses": [
                {
                    "dataPoints": [
                        {
                            "heartRate": {
                                "sampleTime": {"physicalTime": "invalid"},
                                "beatsPerMinute": 80,
                            }
                        }
                    ]
                }
            ]
        },
    )

    # Act / Assert
    with pytest.raises(ValueError, match="invalid_raw_google_health_record"):
        replay_google_health_raw(writer, reset_compacted=True)
    rows = pd.read_parquet(BytesIO(memory_s3.objects[compacted_key]))
    assert rows.iloc[0]["value"] == 72.0
