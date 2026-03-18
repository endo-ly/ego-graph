"""Compact parquet path resolution tests."""

from datetime import date

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

    def test_prefers_local_compacted_file_when_present(self, tmp_path):
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
            data_domain="events",
            dataset_path="spotify/plays",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        assert paths == [str(local_file)]

    def test_falls_back_to_r2_when_local_file_missing(self, tmp_path):
        config = _build_r2_config(local_parquet_root=str(tmp_path))

        paths = build_partition_paths(
            config,
            data_domain="events",
            dataset_path="spotify/plays",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        assert paths == [
            "s3://test-bucket/compacted/events/spotify/plays/year=2024/month=01/data.parquet"
        ]


class TestBuildDatasetGlob:
    """build_dataset_glob tests."""

    def test_prefers_local_glob_when_compacted_files_exist(self, tmp_path):
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
            data_domain="master",
            dataset_path="spotify/tracks",
        )

        assert path == str(
            tmp_path
            / "compacted"
            / "master"
            / "spotify"
            / "tracks"
            / "**"
            / "*.parquet"
        )

    def test_uses_r2_glob_when_local_dataset_missing(self, tmp_path):
        config = _build_r2_config(local_parquet_root=str(tmp_path))

        path = build_dataset_glob(
            config,
            data_domain="master",
            dataset_path="spotify/tracks",
        )

        assert path == "s3://test-bucket/compacted/master/spotify/tracks/**/*.parquet"
