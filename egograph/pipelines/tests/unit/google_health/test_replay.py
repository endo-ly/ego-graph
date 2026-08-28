"""Google Health Raw replayのテスト。"""

from datetime import date
from io import BytesIO
from unittest.mock import patch

import pandas as pd
from botocore.exceptions import ClientError
from pipelines.sources.google_health.replay import replay_google_health_raw
from pipelines.sources.google_health.writer import GoogleHealthWriter


class MemoryS3:
    """Raw/events/compactedを保持するin-memory S3。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"

        class Paginator:
            def __init__(self, objects):
                self.objects = objects

            def paginate(self, *, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": key}
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
