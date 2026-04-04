"""Local mirror sync pipeline tests."""

from pathlib import Path

from botocore.exceptions import ClientError
from pipelines.sources.common.config import R2Config
from pipelines.sources.local_mirror_sync.pipeline import run_local_mirror_sync
from pydantic import SecretStr


class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        return self._pages


class _FakeS3Client:
    def __init__(self, pages, objects, fail_keys=()):
        self._pages = pages
        self._objects = objects
        self._fail_keys = set(fail_keys)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _FakePaginator(self._pages)

    def download_file(self, bucket, key, filename):
        assert bucket == "egograph"
        if key in self._fail_keys:
            raise ClientError(
                {
                    "Error": {
                        "Code": "InternalError",
                        "Message": "download failed",
                    }
                },
                "DownloadFile",
            )
        Path(filename).write_bytes(self._objects[key])


def test_run_local_mirror_sync_downloads_skips_and_reports_failures(
    monkeypatch,
    tmp_path,
):
    """同期結果を summary フィールドとして返す。"""
    github_key = "compacted/events/github/commits/year=2026/month=04/data.parquet"
    spotify_key = "compacted/events/spotify/plays/year=2026/month=04/data.parquet"
    browser_history_key = (
        "compacted/events/browser_history/page_views/year=2026/month=04/data.parquet"
    )

    local_root = tmp_path / "parquet"
    existing = local_root / github_key
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"already")

    fake_client = _FakeS3Client(
        pages=[
            {
                "Contents": [
                    {
                        "Key": github_key,
                        "Size": 7,
                    },
                    {
                        "Key": spotify_key,
                        "Size": 3,
                    },
                    {
                        "Key": browser_history_key,
                        "Size": 5,
                    },
                ]
            }
        ],
        objects={
            spotify_key: b"new",
        },
        fail_keys=(browser_history_key,),
    )
    monkeypatch.setattr(
        "pipelines.sources.local_mirror_sync.pipeline.boto3.client",
        lambda *args, **kwargs: fake_client,
    )

    result = run_local_mirror_sync(
        r2_config=R2Config(
            endpoint_url="https://r2.example.com",
            access_key_id="access-key",
            secret_access_key=SecretStr("secret"),
            bucket_name="egograph",
            local_parquet_root=str(local_root),
        ),
    )

    assert result.downloaded_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 1
    assert result.failed_keys_sample == (browser_history_key,)
    assert result.last_success_at is None
    assert (
        local_root / "compacted/events/spotify/plays/year=2026/month=04/data.parquet"
    ).read_bytes() == b"new"
    assert result.to_summary_dict() == {
        "target_prefix": "compacted/",
        "downloaded_count": 1,
        "skipped_count": 1,
        "failed_count": 1,
        "failed_keys_sample": (browser_history_key,),
        "last_success_at": None,
    }
