"""Global Recompactのテスト。"""

from datetime import UTC, datetime
from io import BytesIO

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from dataset_catalog import ALL_DATASETS, iter_datasets
from pipelines.maintenance.progress import NullProgressReporter
from pipelines.maintenance.recompact import (
    RecompactRequest,
    RecompactService,
)


class MemoryS3:
    """Parquetオブジェクトを保持するin-memory S3。"""

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
        objects = self.objects

        class Paginator:
            def paginate(self, *, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": key}
                        for key in sorted(objects)
                        if key.startswith(Prefix)
                    ]
                }

        return Paginator()


def _put_parquet(s3: MemoryS3, key: str, rows: list[dict]) -> None:
    buffer = BytesIO()
    pd.DataFrame(rows).to_parquet(buffer, index=False, engine="pyarrow")
    s3.objects[key] = buffer.getvalue()


def _spotify_play(play_id: str, name: str, played_at: str) -> dict:
    return {
        "play_id": play_id,
        "played_at_utc": played_at,
        "track_id": f"track-{play_id}",
        "track_name": name,
    }


def _service(s3: MemoryS3, **kwargs) -> RecompactService:
    return RecompactService(
        s3_client=s3,
        bucket_name="bucket",
        progress=NullProgressReporter(),
        **kwargs,
    )


def test_append_dedupe_recompacts_one_source_partition_at_a_time():
    """月次sourceをdedupeしてcompactし、重複IDは最新sort値を残す。"""
    # Arrange
    s3 = MemoryS3()
    _put_parquet(
        s3,
        "events/spotify/plays/year=2026/month=06/a.parquet",
        [_spotify_play("play-1", "old", "2026-06-01T10:00:00Z")],
    )
    _put_parquet(
        s3,
        "events/spotify/plays/year=2026/month=06/b.parquet",
        [
            _spotify_play("play-1", "new", "2026-06-01T11:00:00Z"),
            _spotify_play("play-2", "second", "2026-06-02T10:00:00Z"),
        ],
    )

    # Act
    result = _service(s3).run(
        RecompactRequest(dataset_id="spotify.plays", year=2026, month=6)
    )

    # Assert
    assert result.status == "succeeded"
    assert result.targets[0].partition_count == 1
    key = "compacted/events/spotify/plays/year=2026/month=06/data.parquet"
    rows = pd.read_parquet(BytesIO(s3.objects[key])).to_dict(orient="records")
    assert {row["play_id"]: row["track_name"] for row in rows} == {
        "play-1": "new",
        "play-2": "second",
    }


def test_month_selector_does_not_touch_other_partitions():
    """年月指定時は対象月以外のcompact済みpartitionを保持する。"""
    # Arrange
    s3 = MemoryS3()
    june_source = "events/spotify/plays/year=2026/month=06/source.parquet"
    july_compacted = (
        "compacted/events/spotify/plays/year=2026/month=07/data.parquet"
    )
    _put_parquet(s3, june_source, [_spotify_play("june", "June", "2026-06-01")])
    _put_parquet(s3, july_compacted, [_spotify_play("july", "July", "2026-07-01")])

    # Act
    _service(s3).run(
        RecompactRequest(dataset_id="spotify.plays", year=2026, month=6)
    )

    # Assert
    assert july_compacted in s3.objects


def test_prune_removes_stale_month_only_after_successful_rebuild():
    """pruneはrebuild成功後にsourceにない月だけを削除する。"""
    # Arrange
    s3 = MemoryS3()
    stale_key = "compacted/events/spotify/plays/year=2026/month=07/data.parquet"
    _put_parquet(s3, "events/spotify/plays/year=2026/month=06/source.parquet", [])
    _put_parquet(s3, stale_key, [_spotify_play("stale", "Stale", "2026-07-01")])

    # Act
    result = _service(s3).run(
        RecompactRequest(dataset_id="spotify.plays", prune=True)
    )

    # Assert
    assert result.status == "succeeded"
    assert stale_key not in s3.objects


def test_snapshot_upsert_writes_catalog_snapshot_key():
    """snapshot sourceを固定compact snapshot keyへ再生成する。"""
    # Arrange
    s3 = MemoryS3()
    _put_parquet(
        s3,
        "master/youtube/videos/data.parquet",
        [
            {
                "video_id": "video-1",
                "title": "Video",
                "updated_at": datetime(2026, 8, 1, tzinfo=UTC),
            }
        ],
    )

    # Act
    result = _service(s3).run(
        RecompactRequest(dataset_id="youtube.videos")
    )

    # Assert
    assert result.status == "succeeded"
    key = "compacted/master/youtube/videos/data.parquet"
    assert key in s3.objects
    assert pd.read_parquet(BytesIO(s3.objects[key])).iloc[0]["video_id"] == "video-1"


def test_none_strategy_is_reported_as_explicit_skip():
    """NONE datasetは処理せずskip結果を返す。"""
    # Arrange
    s3 = MemoryS3()

    # Act
    result = _service(s3).run(
        RecompactRequest(dataset_id="github.repositories")
    )

    # Assert
    target = result.targets[0]
    assert result.status == "succeeded"
    assert target.status == "skipped"
    assert target.reason == "compaction_strategy_none"


def test_range_replace_is_delegated_to_google_health_adapter(monkeypatch):
    """Google Healthはgeneric dedupeではなくRaw replay adapterへ委譲する。"""
    # Arrange
    captured: dict[str, object] = {}

    def fake_replay(writer, **kwargs):
        captured["writer"] = writer
        captured.update(kwargs)
        return {"compacted_partition_counts": {"google_health.samples": 3}}

    monkeypatch.setattr(
        "pipelines.maintenance.recompact.replay_google_health_raw",
        fake_replay,
    )
    writer = object()

    # Act
    result = _service(s3=MemoryS3(), google_health_writer=writer).run(
        RecompactRequest(dataset_id="google_health.samples")
    )

    # Assert
    assert result.status == "succeeded"
    assert captured["writer"] is writer
    assert captured["selected_dataset_ids"] == ("google_health.samples",)
    assert captured["reset_compacted"] is True
    assert result.targets[0].partition_count == 3


def test_global_recompact_continues_after_dataset_failure(monkeypatch):
    """1 datasetの失敗で後続datasetを停止せずpartial_failedにする。"""
    # Arrange
    service = _service(MemoryS3())
    processed: list[str] = []

    def fake_recompact(dataset, request):
        processed.append(dataset.dataset_id)
        if dataset.dataset_id == "spotify.plays":
            raise RuntimeError("simulated failure")
        return 0

    monkeypatch.setattr(service, "_recompact_monthly", fake_recompact)

    # Act
    result = service.run(RecompactRequest(provider="spotify"))

    # Assert
    assert result.status == "partial_failed"
    assert result.failed == 1
    assert result.succeeded == 2
    assert processed == ["spotify.plays", "spotify.tracks", "spotify.artists"]


def test_request_validates_supported_filters():
    """正常なprovider filterを受け付ける。"""
    # Arrange / Act
    result = RecompactRequest(provider="spotify")

    # Assert
    assert result.provider == "spotify"


def test_request_rejects_provider_and_dataset_together():
    """providerとdatasetの同時指定を拒否する。"""
    with pytest.raises(ValueError, match="invalid_filters"):
        RecompactRequest(provider="spotify", dataset_id="spotify.plays")


def test_request_rejects_year_without_month():
    """yearだけの指定を拒否する。"""
    with pytest.raises(ValueError, match="invalid_date_range"):
        RecompactRequest(year=2026)


def test_catalog_iterator_is_the_source_of_all_dataset_definitions():
    """Catalog iteratorが既存のALL_DATASETSと同じ定義順を返す。"""
    # Arrange / Act
    result = iter_datasets()

    # Assert
    assert result == ALL_DATASETS
    assert len({dataset.dataset_id for dataset in result}) == len(result)
