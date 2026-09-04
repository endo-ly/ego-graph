"""Google Health Raw replayのテスト。"""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from pipelines.maintenance.progress import ProgressReporter
from pipelines.sources.google_health import replay as replay_module
from pipelines.sources.google_health.replay import replay_google_health_raw
from pipelines.sources.google_health.writer import GoogleHealthWriter


class MemoryS3:
    """Raw/events/compactedを保持するin-memory S3。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.last_modified: dict[str, datetime] = {}
        self._write_count = 0

    def upload_fileobj(
        self,
        Fileobj,
        Bucket,
        Key,
        *,
        ExtraArgs,
        Config,
    ):  # noqa: N803
        self.objects[Key] = Fileobj.read()
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


class GuardedRawBody(BytesIO):
    """全量readを検出するRaw JSON body。"""

    def read(self, size=-1):
        if size == -1:
            raise AssertionError("Raw replay must not read the whole body")
        return super().read(size)


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


class RecordingProgress(ProgressReporter):
    """進捗通知の順序を記録する。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, int, int, str]] = []

    def report(self, phase: str, current: int, total: int, label: str) -> None:
        self.events.append((phase, current, total, label))


def _heart_rate_payload(value: int, timestamp: str) -> dict:
    return {
        "reconcileResponses": [
            {
                "dataPoints": [
                    {
                        "heartRate": {
                            "sampleTime": {"physicalTime": timestamp},
                            "beatsPerMinute": value,
                        }
                    }
                ]
            }
        ]
    }


def _large_heart_rate_payload(point_count: int) -> dict:
    """streaming replay検証用のheart-rate Rawを作る。"""
    started_at = datetime(2026, 6, 1, tzinfo=UTC)
    return {
        "reconcileResponses": [
            {
                "dataPoints": [
                    {
                        "dataPointName": f"heart-rate-{index}",
                        "heartRate": {
                            "sampleTime": {
                                "physicalTime": (started_at + timedelta(seconds=index))
                                .isoformat()
                                .replace("+00:00", "Z")
                            },
                            "beatsPerMinute": 60 + index % 40,
                        },
                    }
                    for index in range(point_count)
                ]
            }
        ]
    }


def _session_point(
    data_type: str,
    session_id: str,
    started_at: str,
    ended_at: str,
) -> dict:
    """テスト用のsleep/exercise DataPointを作る。"""
    return {
        "dataPointName": session_id,
        data_type: {
            "interval": {
                "startTime": started_at,
                "endTime": ended_at,
            },
            "type": data_type.upper(),
        },
    }


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
    assert first["compacted_partition_counts"] == {
        "google_health.records": 1,
        "google_health.daily_metrics": 0,
        "google_health.samples": 1,
        "google_health.intervals": 0,
        "google_health.sessions": 0,
    }
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )
    rows = pd.read_parquet(BytesIO(memory_s3.objects[compacted_key]))
    assert len(rows) == 1
    assert rows.iloc[0]["value"] == 72.0
    assert any("archive/google_health/" in key for key in memory_s3.objects)


def test_replay_streams_large_raw_in_bounded_chunks_without_second_raw_read(
    monkeypatch,
):
    """大きなRawを全量readせず、chunk単位で一度だけ正規化する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    raw_key = writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="large-run",
        payload=_large_heart_rate_payload(20_001),
    )
    raw_body = memory_s3.objects[raw_key]
    original_get_object = memory_s3.get_object
    raw_get_count = 0

    def get_object(*, Bucket, Key):  # noqa: N803
        nonlocal raw_get_count
        if Key == raw_key:
            raw_get_count += 1
            return {"Body": GuardedRawBody(raw_body)}
        return original_get_object(Bucket=Bucket, Key=Key)

    monkeypatch.setattr(memory_s3, "get_object", get_object)
    original_normalize = replay_module.normalize_google_health_payload
    chunk_sizes: list[int] = []

    def record_normalize(**kwargs):
        payload = kwargs["payload"]
        points = payload.get("reconcileResponses", [])[0]["dataPoints"]
        chunk_sizes.append(len(points))
        return original_normalize(**kwargs)

    monkeypatch.setattr(
        replay_module,
        "normalize_google_health_payload",
        record_normalize,
    )

    # Act
    result = replay_google_health_raw(writer, reset_compacted=True)

    # Assert
    assert result["raw_count"] == 1
    assert raw_get_count == 1
    assert chunk_sizes == [5_000, 5_000, 5_000, 5_000, 1]


def test_replay_keeps_existing_compacted_when_late_chunk_fails(monkeypatch):
    """後半chunkの失敗時はeventsとcompactedを変更しない。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    raw_key = writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="late-failure-run",
        payload=_large_heart_rate_payload(5_001),
    )
    replay_google_health_raw(writer, reset_compacted=True)
    compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )
    original_compacted = memory_s3.objects[compacted_key]
    original_event_keys = {key for key in memory_s3.objects if "raw-replay-" in key}
    original_normalize = replay_module.normalize_google_health_payload
    normalize_count = 0

    def fail_on_second_chunk(**kwargs):
        nonlocal normalize_count
        normalize_count += 1
        if normalize_count == 2:
            raise ValueError("normalization failed")
        return original_normalize(**kwargs)

    monkeypatch.setattr(
        replay_module,
        "normalize_google_health_payload",
        fail_on_second_chunk,
    )
    reset_compacted = Mock(wraps=writer.reset_compacted)
    writer.reset_compacted = reset_compacted

    # Act / Assert
    with pytest.raises(ValueError, match="normalization failed"):
        replay_google_health_raw(writer, reset_compacted=True)
    assert reset_compacted.call_count == 0
    assert memory_s3.objects[compacted_key] == original_compacted
    assert {
        key for key in memory_s3.objects if "raw-replay-" in key
    } == original_event_keys
    assert raw_key in memory_s3.objects


def test_replay_removes_stale_event_when_projection_becomes_empty(monkeypatch):
    """再Replayで空になったprojectionの古いeventを削除する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-1",
        payload=_heart_rate_payload(72, "2026-06-01T01:00:00Z"),
    )
    replay_google_health_raw(writer, reset_compacted=True)
    samples_prefix = "events/google_health/samples/year=2026/month=06/"
    samples_compacted_key = (
        "compacted/events/google_health/samples/year=2026/month=06/data.parquet"
    )
    assert any(key.startswith(samples_prefix) for key in memory_s3.objects)
    assert samples_compacted_key in memory_s3.objects

    original_normalize = replay_module.normalize_google_health_payload

    def normalize_without_samples(**kwargs):
        normalized = original_normalize(**kwargs)
        normalized["samples"] = []
        return normalized

    monkeypatch.setattr(
        replay_module,
        "normalize_google_health_payload",
        normalize_without_samples,
    )

    # Act
    replay_google_health_raw(writer, reset_compacted=True)

    # Assert
    assert not any(key.startswith(samples_prefix) for key in memory_s3.objects)
    assert samples_compacted_key not in memory_s3.objects


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


def test_replay_preserves_daily_rollup_for_interval_data_type():
    """DailyRollup専用のinterval data typeもdaily projectionを保存する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type="calories-in-heart-rate-zone",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="calories-run",
        payload={
            "rollupResponses": [
                {
                    "rollupDataPoints": [
                        {
                            "startTime": "2026-06-01T00:00:00Z",
                            "endTime": "2026-06-01T00:05:00Z",
                            "caloriesInHeartRateZone": {"kilocaloriesSum": "2.5"},
                        }
                    ]
                }
            ],
            "dailyRollupResponses": [
                {
                    "rollupDataPoints": [
                        {
                            "civilStartTime": {
                                "date": {"year": 2026, "month": 6, "day": 1}
                            },
                            "caloriesInHeartRateZone": {
                                "caloriesInHeartRateZones": [
                                    {"heartRateZone": "CARDIO", "kcal": 30.0}
                                ]
                            },
                        }
                    ]
                }
            ],
        },
    )

    # Act
    replay_google_health_raw(writer, reset_compacted=True)

    # Assert
    interval_path = (
        "compacted/events/google_health/intervals/year=2026/month=06/data.parquet"
    )
    daily_path = (
        "compacted/events/google_health/daily_metrics/year=2026/month=06/data.parquet"
    )
    intervals = pd.read_parquet(BytesIO(memory_s3.objects[interval_path]))
    daily = pd.read_parquet(BytesIO(memory_s3.objects[daily_path]))
    assert intervals.iloc[0]["value"] == 2.5
    assert {(row["metric_name"], row["value"]) for _, row in daily.iterrows()} == {
        ("calories_in_heart_rate_zone_cardio", 30.0)
    }


def test_replay_aggregates_daily_metrics_within_each_raw_entry():
    """Raw Entry内の複数sessionを通常ingestと同じ日次値へ集約する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type="sleep",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="sleep-run",
        payload={
            "reconcileResponses": [
                {
                    "dataPoints": [
                        _session_point(
                            "sleep",
                            "sleep-1",
                            "2026-06-01T00:00:00Z",
                            "2026-06-01T06:00:00Z",
                        ),
                        _session_point(
                            "sleep",
                            "sleep-2",
                            "2026-06-01T06:00:00Z",
                            "2026-06-01T07:00:00Z",
                        ),
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
    sessions_path = (
        "compacted/events/google_health/sessions/year=2026/month=06/data.parquet"
    )
    daily = pd.read_parquet(BytesIO(memory_s3.objects[daily_path]))
    sessions = pd.read_parquet(BytesIO(memory_s3.objects[sessions_path]))
    assert len(daily) == 1
    assert daily.iloc[0]["metric_name"] == "sleep_duration"
    assert daily.iloc[0]["value"] == 7 * 60 * 60
    assert len(sessions) == 2


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


def test_replay_normalizes_one_entry_at_a_time_and_uses_deterministic_event_ids():
    """全Rawを保持せず、Raw Entryごとに保存・compactする。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    for run_id, value in (("run-1", 72), ("run-2", 74)):
        writer.save_raw(
            connection_id="connection-1",
            data_type="heart-rate",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 2),
            run_id=run_id,
            payload=_heart_rate_payload(value, "2026-06-01T01:00:00Z"),
        )
    progress = RecordingProgress()
    events: list[str] = []
    writer.reset_compacted = Mock(side_effect=lambda **_: events.append("reset"))

    def record_save(**kwargs):
        events.append("save")
        return []

    writer.replace_events_from_parquet = Mock(side_effect=record_save)

    def record_compact(**kwargs):
        events.append("compact")
        return []

    writer.compact_range = Mock(side_effect=record_compact)

    # Act
    result = replay_google_health_raw(
        writer,
        reset_compacted=True,
        progress=progress,
    )

    # Assert
    assert result["raw_count"] == 2
    assert progress.events == [
        ("validate", 1, 2, "heart-rate"),
        ("validate", 2, 2, "heart-rate"),
        ("replay", 1, 2, "heart-rate"),
        ("replay", 2, 2, "heart-rate"),
    ]
    assert events == ["save", "save", "reset", "compact", "compact"]
    save_ids = [
        call.kwargs["run_id"]
        for call in writer.replace_events_from_parquet.call_args_list
    ]
    compact_ids = [
        call.kwargs["run_id"] for call in writer.compact_range.call_args_list
    ]
    assert save_ids == compact_ids
    assert len(set(save_ids)) == 2
    assert all(event_id.startswith("raw-replay-") for event_id in save_ids)


def test_replay_compacts_only_datasets_a_data_type_can_generate():
    """Raw Entryごとに不要なProjection Datasetをcompactしない。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-1",
        payload=_heart_rate_payload(72, "2026-06-01T01:00:00Z"),
    )
    writer.replace_events_from_parquet = Mock(return_value=[])
    writer.compact_range = Mock(return_value=[])

    # Act
    replay_google_health_raw(writer, progress=RecordingProgress())

    # Assert
    expected = (
        "google_health.records",
        "google_health.daily_metrics",
        "google_health.samples",
    )
    assert (
        writer.replace_events_from_parquet.call_args.kwargs["selected_dataset_ids"]
        == expected
    )
    assert writer.compact_range.call_args.kwargs["selected_dataset_ids"] == expected


def test_replay_compacts_empty_normalization_to_replace_no_data():
    """正規化結果が空でも対象rangeのcompactを実行する。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-empty",
        payload={"reconcileResponses": []},
    )
    writer.replace_events_from_parquet = Mock(return_value=[])
    writer.compact_range = Mock(return_value=[])

    # Act
    replay_google_health_raw(writer, progress=RecordingProgress())

    # Assert
    writer.replace_events_from_parquet.assert_called_once()
    writer.compact_range.assert_called_once()


def test_replay_reports_raw_key_for_stream_parse_error():
    """streaming parseエラーに対象Raw keyを含める。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    raw_key = writer.save_raw(
        connection_id="connection-1",
        data_type="heart-rate",
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        run_id="run-invalid-json",
        payload={"reconcileResponses": []},
    )
    memory_s3.objects[raw_key] = b'{"reconcileResponses": ['

    # Act
    with pytest.raises(ValueError) as exc_info:
        replay_google_health_raw(writer)

    # Assert
    assert str(exc_info.value) == f"invalid_raw_google_health_json: {raw_key}"


@pytest.mark.parametrize(
    ("data_type", "started_at", "ended_at", "included"),
    [
        (
            "exercise",
            "2026-07-31T23:30:00Z",
            "2026-08-01T00:30:00Z",
            False,
        ),
        (
            "exercise",
            "2026-08-31T23:30:00Z",
            "2026-09-01T00:30:00Z",
            True,
        ),
        (
            "sleep",
            "2026-07-31T23:30:00Z",
            "2026-08-01T07:30:00Z",
            True,
        ),
    ],
)
def test_partial_replay_uses_semantic_session_target_date(
    data_type,
    started_at,
    ended_at,
    included,
):
    """月指定Replayのsession対象日をsleepとexerciseで使い分ける。"""
    # Arrange
    memory_s3 = MemoryS3()
    writer = _writer(memory_s3)
    writer.save_raw(
        connection_id="connection-1",
        data_type=data_type,
        date_from=date(2026, 7, 31),
        date_to=date(2026, 9, 2),
        run_id=f"{data_type}-run",
        payload={
            "reconcileResponses": [
                {
                    "dataPoints": [
                        _session_point(
                            data_type,
                            f"{data_type}-1",
                            started_at,
                            ended_at,
                        )
                    ]
                }
            ]
        },
    )
    writer.replace_events_from_parquet = Mock(return_value=[])
    writer.compact_range = Mock(return_value=[])

    # Act
    replay_google_health_raw(
        writer,
        selected_dataset_ids=("google_health.sessions",),
        date_from=date(2026, 8, 1),
        date_to=date(2026, 9, 1),
        progress=RecordingProgress(),
    )

    # Assert
    event_files = writer.replace_events_from_parquet.call_args.kwargs["event_files"]
    session_files = event_files.get("sessions", {})
    sessions = [path for path in session_files.values()]
    assert bool(sessions) is included
