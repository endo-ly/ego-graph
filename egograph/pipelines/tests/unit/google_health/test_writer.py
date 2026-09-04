"""Google Health writerのテスト。"""

import logging
from datetime import UTC, date, datetime
from io import BytesIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from pipelines.sources.google_health.writer import (
    MULTIPART_CHUNK_SIZE_BYTES,
    MULTIPART_THRESHOLD_BYTES,
    GoogleHealthWriter,
)


class MemoryS3:
    """events保存とcompactionを検証するin-memory S3。"""

    def __init__(self):
        self.objects = {}
        self.upload_calls = []
        self.fail_upload_key = None
        self.fail_after_upload_key = None
        self.fail_delete_key = None

    def upload_fileobj(
        self,
        Fileobj,
        Bucket,
        Key,
        *,
        ExtraArgs,
        Config,
    ):  # noqa: N803
        self.upload_calls.append(
            {
                "key": Key,
                "content_type": ExtraArgs["ContentType"],
                "config": Config,
            }
        )
        data = Fileobj.read()
        if Key == self.fail_upload_key:
            raise RuntimeError("upload failed")
        self.objects[Key] = data
        if Key == self.fail_after_upload_key:
            raise RuntimeError("upload failed after save")

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        if Key == self.fail_delete_key:
            raise RuntimeError("delete failed")
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
        "record_id": "rec-sample-1",
        "connection_id": "google-health-primary",
        "data_type": "heart-rate",
        "metric_name": "heart_rate",
        "measured_at_utc": datetime(2026, 6, 1, tzinfo=UTC),
        "value": 75.0,
        "unit": "beats_per_minute",
        "device_family": "fitbit_air",
        "raw_ref": "raw/google_health/example.json",
        "ingested_at_utc": datetime(2026, 6, 4, tzinfo=UTC),
    }
    row.update(overrides)
    return row


def _daily_metric_row(**overrides) -> dict:
    """schema 契約を満たす google_health.daily_metrics 行。"""
    row = {
        "record_id": "rec-daily-1",
        "connection_id": "google-health-primary",
        "data_type": "daily-resting-heart-rate",
        "date": date(2026, 6, 1),
        "metric_name": "daily_resting_heart_rate",
        "value": 60.0,
        "unit": "beats_per_minute",
        "device_family": "fitbit_air",
        "raw_ref": "raw/google_health/example.json",
        "ingested_at_utc": datetime(2026, 6, 4, tzinfo=UTC),
    }
    row.update(overrides)
    return row


def _record_row(**overrides) -> dict:
    """schema 契約を満たす google_health.records 行。"""
    row = {
        "record_id": "rec-record-1",
        "source_record_id": "source-record-1",
        "connection_id": "google-health-primary",
        "data_type": "heart-rate",
        "record_kind": "sample",
        "record_date": date(2026, 6, 1),
        "payload_json": '{"heartRate":{"beatsPerMinute":75}}',
        "device_family": "fitbit_air",
        "raw_ref": "raw/google_health/example.json",
        "ingested_at_utc": datetime(2026, 6, 4, tzinfo=UTC),
    }
    row.update(overrides)
    return row


def _session_row(**overrides) -> dict:
    """schema 契約を満たす google_health.sessions 行。"""
    row = {
        "record_id": "rec-session-1",
        "connection_id": "google-health-primary",
        "data_type": "sleep",
        "session_id": "session-1",
        "started_at_utc": datetime(2026, 5, 31, 23, tzinfo=UTC),
        "ended_at_utc": datetime(2026, 6, 1, 7, tzinfo=UTC),
        "duration_seconds": 28800,
        "session_type": "sleep",
        "device_family": "fitbit_air",
        "raw_ref": "raw/google_health/example.json",
        "ingested_at_utc": datetime(2026, 6, 4, tzinfo=UTC),
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
    assert memory_s3.objects[key] == b'{"dataPoints":[]}'


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
        records={"samples": [_sample_row()]},
    )

    # Assert
    assert saved_keys == [
        "events/google_health/samples/year=2026/month=06/run-1.parquet"
    ]
    assert old_key in memory_s3.objects


def test_transfer_config_uses_managed_multipart_settings():
    """managed multipartのthreshold、part size、thread設定を固定する。"""
    # Arrange
    memory_s3 = MemoryS3()

    # Act
    writer = _writer(memory_s3)

    # Assert
    assert writer._transfer_config.multipart_threshold == MULTIPART_THRESHOLD_BYTES
    assert writer._transfer_config.multipart_chunksize == MULTIPART_CHUNK_SIZE_BYTES
    assert writer._transfer_config.use_threads is False


def test_upload_logs_key_size_and_multipart_decision(caplog):
    """upload開始・完了ログに診断用metadataだけを記録する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    caplog.set_level(
        logging.INFO,
        logger="pipelines.sources.google_health.writer",
    )

    # Act
    writer._upload_bytes(
        key="events/google_health/samples/example.parquet",
        data=b"payload",
        content_type="application/octet-stream",
    )

    # Assert
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "R2 upload started: key=events/google_health/samples/example.parquet "
        "size_bytes=7 multipart=False" in message
        for message in messages
    )
    assert any(
        "R2 upload completed: key=events/google_health/samples/example.parquet "
        "size_bytes=7 multipart=False duration_seconds=" in message
        for message in messages
    )


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
            _sample_row(value=70.0),
            _sample_row(
                record_id="rec-sample-2",
                data_type="oxygen-saturation",
                metric_name="oxygen_saturation",
                unit="percent",
                value=95.0,
            ),
        ],
    )
    _put_parquet(
        memory_s3,
        event_key,
        [
            _sample_row(measured_at_utc=datetime(2026, 6, 1, 2, tzinfo=UTC)),
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


def test_save_events_cleans_up_all_attempted_run_keys_on_upload_failure():
    """eventsの途中upload失敗時はそのrunの全試行キーを削除する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    previous_key = (
        "events/google_health/samples/year=2026/month=06/previous-run.parquet"
    )
    failed_key = "events/google_health/samples/year=2026/month=06/run-1.parquet"
    memory_s3.objects[previous_key] = b"previous"
    memory_s3.fail_upload_key = failed_key
    records = {
        "records": [_record_row()],
        "daily_metrics": [_daily_metric_row()],
        "samples": [_sample_row()],
    }

    # Act / Assert
    with pytest.raises(RuntimeError, match="upload failed"):
        writer.save_events(
            run_id="run-1",
            records=records,
            selected_dataset_ids=(
                "google_health.records",
                "google_health.daily_metrics",
                "google_health.samples",
            ),
        )

    assert not any(key.endswith("/run-1.parquet") for key in memory_s3.objects)
    assert previous_key in memory_s3.objects


def test_save_events_cleans_up_key_when_upload_fails_after_object_is_saved():
    """応答前に保存済みとなったfailed uploadもcleanup対象にする。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    key = "events/google_health/samples/year=2026/month=06/run-1.parquet"
    memory_s3.fail_after_upload_key = key

    # Act / Assert
    with pytest.raises(RuntimeError, match="upload failed after save"):
        writer.save_events(
            run_id="run-1",
            records={"samples": [_sample_row()]},
        )

    assert key not in memory_s3.objects


def test_save_events_preserves_upload_error_when_cleanup_fails(caplog):
    """cleanup失敗時も元のupload errorをraiseし、cleanup errorを記録する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    failed_key = "events/google_health/samples/year=2026/month=06/run-1.parquet"
    memory_s3.fail_upload_key = failed_key
    memory_s3.fail_delete_key = failed_key
    caplog.set_level(
        logging.ERROR,
        logger="pipelines.sources.google_health.writer",
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="upload failed"):
        writer.save_events(
            run_id="run-1",
            records={"samples": [_sample_row()]},
        )

    assert any(
        record.getMessage() == "Google Health event cleanup failed: key=" + failed_key
        for record in caplog.records
    )


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
        [_sample_row(value=70.0)],
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
        [_sample_row(measured_at_utc=datetime(2026, 5, 31, 15, 30, tzinfo=UTC))],
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


@pytest.mark.parametrize(
    ("data_type", "started_at", "ended_at", "expected_current"),
    [
        (
            "exercise",
            datetime(2026, 7, 31, 23, 30, tzinfo=UTC),
            datetime(2026, 8, 1, 0, 30, tzinfo=UTC),
            False,
        ),
        (
            "exercise",
            datetime(2026, 8, 31, 23, 30, tzinfo=UTC),
            datetime(2026, 9, 1, 0, 30, tzinfo=UTC),
            True,
        ),
        (
            "sleep",
            datetime(2026, 7, 31, 23, 30, tzinfo=UTC),
            datetime(2026, 8, 1, 7, 30, tzinfo=UTC),
            True,
        ),
    ],
)
def test_compact_range_uses_semantic_session_target_date(
    data_type,
    started_at,
    ended_at,
    expected_current,
):
    """sessionのrange replace日をsleepは終了、exerciseは開始で判定する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    month = started_at.month
    event_key = (
        f"events/google_health/sessions/year=2026/month={month:02d}/run-1.parquet"
    )
    compacted_key = (
        "compacted/events/google_health/sessions/year=2026/"
        f"month={month:02d}/data.parquet"
    )
    _put_parquet(
        memory_s3,
        compacted_key,
        [
            _session_row(
                record_id="old",
                session_id="old",
                data_type=data_type,
                session_type=data_type,
                started_at_utc=started_at,
                ended_at_utc=ended_at,
            )
        ],
    )
    _put_parquet(
        memory_s3,
        event_key,
        [
            _session_row(
                record_id="current",
                session_id="current",
                data_type=data_type,
                session_type=data_type,
                started_at_utc=started_at,
                ended_at_utc=ended_at,
            )
        ],
    )

    # Act
    writer.compact_range(
        connection_id="google-health-primary",
        selected_data_types=(data_type,),
        date_from=date(2026, 8, 1),
        date_to=date(2026, 9, 1),
        run_id="run-1",
    )

    # Assert
    rows = (
        pd.read_parquet(BytesIO(memory_s3.objects[compacted_key])).to_dict(
            orient="records"
        )
        if compacted_key in memory_s3.objects
        else []
    )
    record_ids = {row["record_id"] for row in rows}
    if expected_current:
        assert record_ids == {"current"}
    else:
        assert record_ids == {"old"}


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
