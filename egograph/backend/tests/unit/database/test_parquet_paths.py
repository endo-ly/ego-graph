"""Compact parquet path resolution tests."""

from datetime import datetime

import pytest
from dataset_catalog import datasets
from pydantic import SecretStr

from backend.config import R2Config
from backend.infrastructure.database.parquet_paths import (
    build_dataset_glob,
    build_partition_paths,
)


def _build_r2_config(**overrides) -> R2Config:
    values = {
        "endpoint_url": "https://test.r2.cloudflarestorage.com",
        "access_key_id": "test-key",
        "secret_access_key": SecretStr("test-secret"),
        "bucket_name": "test-bucket",
        "raw_path": "raw/",
        "events_path": "events/",
        "master_path": "master/",
        "local_parquet_root": "/data/parquet",
    }
    values.update(overrides)
    return R2Config.model_construct(**values)


class TestBuildPartitionPaths:
    """build_partition_paths tests."""

    def test_uses_local_for_all_partitions_when_every_partition_is_present(
        self, tmp_path
    ):
        config = _build_r2_config(local_parquet_root=str(tmp_path))
        local_january = (
            tmp_path
            / "compacted"
            / "events"
            / "spotify"
            / "plays"
            / "year=2024"
            / "month=01"
            / "data.parquet"
        )
        local_february = local_january.parent.parent / "month=02" / "data.parquet"
        local_january.parent.mkdir(parents=True)
        local_february.parent.mkdir(parents=True)
        local_january.write_bytes(b"test")
        local_february.write_bytes(b"test")

        paths = build_partition_paths(
            config,
            datasets.SPOTIFY_PLAYS,
            utc_start=datetime(2024, 1, 1),
            utc_end=datetime(2024, 2, 1),
        )

        assert len(paths) == 2  # Jan + Feb (utc_end が次月)
        assert paths == [str(local_january), str(local_february)]

    def test_uses_r2_for_all_partitions_when_one_local_partition_is_missing(
        self, tmp_path
    ):
        config = _build_r2_config(local_parquet_root=str(tmp_path))
        local_file = (
            tmp_path
            / "compacted"
            / "events"
            / "spotify"
            / "plays"
            / "year=2024"
            / "month=01"
            / "data.parquet"
        )
        local_file.parent.mkdir(parents=True)
        local_file.write_bytes(b"test")

        paths = build_partition_paths(
            config,
            datasets.SPOTIFY_PLAYS,
            utc_start=datetime(2024, 1, 1),
            utc_end=datetime(2024, 2, 1),
        )

        assert len(paths) == 2
        assert paths == [
            "s3://test-bucket/compacted/events/spotify/plays/year=2024/month=01/data.parquet",
            "s3://test-bucket/compacted/events/spotify/plays/year=2024/month=02/data.parquet",
        ]

    def test_uses_r2_when_local_mirror_is_disabled(self):
        config = _build_r2_config(local_parquet_root=None)

        paths = build_partition_paths(
            config,
            datasets.SPOTIFY_PLAYS,
            utc_start=datetime(2024, 1, 1),
            utc_end=datetime(2024, 1, 31),
        )

        assert paths == [
            "s3://test-bucket/compacted/events/spotify/plays/year=2024/month=01/data.parquet"
        ]


class TestBuildDatasetGlob:
    """build_dataset_glob tests."""

    def test_uses_r2_glob_when_compacted_files_exist_locally(self, tmp_path):
        config = _build_r2_config(local_parquet_root=str(tmp_path))
        local_file = (
            tmp_path
            / "compacted"
            / "master"
            / "spotify"
            / "tracks"
            / "year=2024"
            / "month=01"
            / "data.parquet"
        )
        local_file.parent.mkdir(parents=True)
        local_file.write_bytes(b"test")

        path = build_dataset_glob(
            config,
            datasets.SPOTIFY_TRACKS,
        )

        assert path == "s3://test-bucket/compacted/master/spotify/tracks/**/*.parquet"

    def test_uses_r2_glob_when_local_dataset_missing(self, tmp_path):
        config = _build_r2_config(local_parquet_root=str(tmp_path))

        path = build_dataset_glob(
            config,
            datasets.SPOTIFY_TRACKS,
        )

        assert path == "s3://test-bucket/compacted/master/spotify/tracks/**/*.parquet"

    @pytest.mark.parametrize(
        "dataset",
        [datasets.GITHUB_REPOSITORIES, datasets.YOUTUBE_VIDEOS],
    )
    def test_uses_r2_glob_for_non_monthly_datasets(self, tmp_path, dataset):
        config = _build_r2_config(local_parquet_root=str(tmp_path))
        local_file = tmp_path / dataset.compacted_prefix("compacted/") / "data.parquet"
        local_file.parent.mkdir(parents=True)
        local_file.write_bytes(b"test")

        path = build_dataset_glob(config, dataset)

        assert path == (
            f"s3://test-bucket/compacted/{dataset.domain.value}/{dataset.path}/**/*.parquet"
        )
