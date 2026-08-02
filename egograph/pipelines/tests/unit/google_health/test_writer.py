"""Google Health writerのテスト。"""

from datetime import UTC, date, datetime
from io import BytesIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from pipelines.sources.google_health.writer import GoogleHealthWriter


class MemoryS3:
    """events保存とcompactionを検証するin-memory S3。"""

    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)


def _writer(memory_s3, *, timezone=None):
    with patch(
        "pipelines.sources.google_health.writer.boto3.client",
        return_value=memory_s3,
    ):
        return GoogleHealthWriter(
            endpoint_url="https://r2.example.test",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            timezone=timezone,
        )


def _put_parquet(memory_s3, key, rows):
    buffer = BytesIO()
    pd.DataFrame(rows).to_parquet(buffer, index=False)
    memory_s3.objects[key] = buffer.getvalue()


def _sample_row(**overrides) -> dict:
    """schema 契約を満たす google_health.samples 行。"""
    row = {
        "connection_id": "google-health-primary",
        "data_type": "heart-rate",
        "measured_at_utc": datetime(2026, 6, 1, tzinfo=UTC),
        "value": 75.0,
    }
    row.update(overrides)
    return row


def _session_row(**overrides) -> dict:
    """schema 契約を満たす google_health.sessions 行。"""
    row = {
        "connection_id": "google-health-primary",
        "data_type": "sleep",
        "session_id": "session-1",
        "started_at_utc": datetime(2026, 5, 31, 23, tzinfo=UTC),
        "ended_at_utc": datetime(2026, 6, 1, 7, tzinfo=UTC),
        "duration_seconds": 28800,
    }
    row.update(overrides)
    return row


def test_raw_key_contains_required_lineage_fields():
    """Raw保存先にconnection、data type、期間、run IDを含める。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)

    # Act
    key = writer.save_raw(
        connection_id="google-health-primary",
        data_type="steps",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 3),
        run_id="run-1",
        payload={"dataPoints": []},
    )

    # Assert
    assert key == (
        "raw/google_health/connection_id=google-health-primary/"
        "data_type=steps/from=2026-06-01/to=2026-06-03/run_id=run-1.json"
    )


def test_save_events_adds_run_file_without_deleting_existing_files():
    """取得ごとのUUID Parquetをeventsへ追加し既存ファイルを残す。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    old_key = "events/google_health/samples/year=2026/month=06/old.parquet"
    memory_s3.objects[old_key] = b"existing"

    # Act
    saved_keys = writer.save_events(
        run_id="run-1",
        records={
            "samples": [
                {
                    "connection_id": "google-health-primary",
                    "data_type": "heart-rate",
                    "measured_at_utc": datetime(2026, 6, 1, tzinfo=UTC),
                    "value": 75.0,
                }
            ]
        },
    )

    # Assert
    assert saved_keys == [
        "events/google_health/samples/year=2026/month=06/run-1.parquet"
    ]
    assert old_key in memory_s3.objects


def test_compact_range_replaces_only_selected_data_type():
    """compacted内の対象期間だけを今回runのeventsで置換する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )
    event_key = "events/google_health/samples/year=2026/month=06/run-1.parquet"
    _put_parquet(
        memory_s3,
        compacted_key,
        [
            {
                "connection_id": "google-health-primary",
                "data_type": "heart-rate",
                "measured_at_utc": datetime(2026, 6, 1, tzinfo=UTC),
                "value": 70.0,
            },
            {
                "connection_id": "google-health-primary",
                "data_type": "oxygen-saturation",
                "measured_at_utc": datetime(2026, 6, 1, tzinfo=UTC),
                "value": 95.0,
            },
        ],
    )
    _put_parquet(
        memory_s3,
        event_key,
        [
            {
                "connection_id": "google-health-primary",
                "data_type": "heart-rate",
                "measured_at_utc": datetime(2026, 6, 1, 2, tzinfo=UTC),
                "value": 75.0,
            }
        ],
    )

    # Act
    saved_keys = writer.compact_range(
        connection_id="google-health-primary",
        selected_data_types=("heart-rate",),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-1",
    )

    # Assert
    assert saved_keys == [compacted_key]
    rows = pd.read_parquet(BytesIO(memory_s3.objects[compacted_key])).to_dict(
        orient="records"
    )
    assert {(row["data_type"], row["value"]) for row in rows} == {
        ("heart-rate", 75.0),
        ("oxygen-saturation", 95.0),
    }
    assert event_key in memory_s3.objects


def test_compact_range_removes_no_data_range_without_deleting_events():
    """no_dataの対象範囲をcompactedから除きeventsファイルは保持する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )
    unrelated_event_key = (
        "events/google_health/samples/year=2026/month=06/previous-run.parquet"
    )
    _put_parquet(
        memory_s3,
        compacted_key,
        [
            {
                "connection_id": "google-health-primary",
                "data_type": "heart-rate",
                "measured_at_utc": datetime(2026, 6, 1, tzinfo=UTC),
                "value": 70.0,
            }
        ],
    )
    memory_s3.objects[unrelated_event_key] = b"existing"

    # Act
    writer.compact_range(
        connection_id="google-health-primary",
        selected_data_types=("heart-rate",),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-with-no-data",
    )

    # Assert
    assert compacted_key not in memory_s3.objects
    assert unrelated_event_key in memory_s3.objects


def test_compact_range_reads_utc_month_crossed_by_local_date():
    """JST日付が跨ぐ前月UTC partitionもcompact対象にする。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3, timezone=ZoneInfo("Asia/Tokyo"))
    event_key = "events/google_health/samples/year=2026/month=05/run-1.parquet"
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=05/data.parquet"
    )
    _put_parquet(
        memory_s3,
        event_key,
        [
            {
                "connection_id": "google-health-primary",
                "data_type": "heart-rate",
                "measured_at_utc": datetime(2026, 5, 31, 15, 30, tzinfo=UTC),
                "value": 75.0,
            }
        ],
    )

    # Act
    writer.compact_range(
        connection_id="google-health-primary",
        selected_data_types=("heart-rate",),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-1",
    )

    # Assert
    assert compacted_key in memory_s3.objects
    rows = pd.read_parquet(BytesIO(memory_s3.objects[compacted_key]))
    assert rows.iloc[0]["value"] == 75.0
    assert event_key in memory_s3.objects


def test_sleep_uses_end_date_for_range_and_start_date_for_partition():
    """月跨ぎsleepは終了日で置換し開始月partitionへ保存する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    event_key = "events/google_health/sessions/year=2026/month=05/run-1.parquet"
    compacted_key = (
        "compacted/events/google_health/sessions/year=2026/month=05/data.parquet"
    )
    _put_parquet(
        memory_s3,
        event_key,
        [
            _session_row(
                started_at_utc=datetime(2026, 5, 31, 23, tzinfo=UTC),
                ended_at_utc=datetime(2026, 6, 1, 7, tzinfo=UTC),
            )
        ],
    )

    # Act
    writer.compact_range(
        connection_id="google-health-primary",
        selected_data_types=("sleep",),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-1",
    )

    # Assert
    rows = pd.read_parquet(BytesIO(memory_s3.objects[compacted_key]))
    assert rows.iloc[0]["duration_seconds"] == 28800
    assert event_key in memory_s3.objects


def test_save_events_raises_without_upload_on_validation_failure():
    """契約違反イベントは検証エラーとなりアップロードされない。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)

    # Act / Assert
    with pytest.raises(ValueError, match="invalid_schema"):
        writer.save_events(
            run_id="run-1",
            records={"samples": [_sample_row(measured_at_utc="2026-06-01T00:00:00Z")]},
        )
    assert not any("run-1.parquet" in key for key in memory_s3.objects)


def test_compact_range_raises_without_upload_on_validation_failure():
    """契約違反のマージ結果は検証エラーとなりcompactedを上書きしない。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )
    event_key = "events/google_health/samples/year=2026/month=06/run-1.parquet"
    _put_parquet(memory_s3, compacted_key, [_sample_row(value=70.0)])
    _put_parquet(memory_s3, event_key, [_sample_row(value="invalid")])

    # Act / Assert
    with pytest.raises(ValueError, match="invalid_schema"):
        writer.compact_range(
            connection_id="google-health-primary",
            selected_data_types=("heart-rate",),
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 2),
            run_id="run-1",
        )
    rows = pd.read_parquet(BytesIO(memory_s3.objects[compacted_key]))
    assert rows.iloc[0]["value"] == 70.0
