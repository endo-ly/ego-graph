"""GitHub compaction のインテグレーションテスト。

MemoryS3 上で ingest 済みのデータに対する compaction (重複排除) を検証する。
"""

import io

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import responses
from pydantic import SecretStr

from pipelines.sources.common.config import (
    Config,
    DuckDBConfig,
    GitHubWorklogConfig,
    R2Config,
)
from pipelines.sources.github.pipeline import (
    run_github_compact,
)
from pipelines.sources.github.storage import GitHubWorklogStorage
from pipelines.tests.e2e.test_browser_history_ingest import (
    _MemoryS3Server,
)


def _build_config(memory_s3) -> Config:
    """GitHub pipeline 用の設定を構築する。"""
    r2 = R2Config(
        endpoint_url=memory_s3.endpoint_url,
        access_key_id="test-access-key",
        secret_access_key=SecretStr("test-secret-key"),
        bucket_name="test-bucket",
    )
    return Config(
        github_worklog=GitHubWorklogConfig(
            token=SecretStr("test-github-token"),
            github_login="test-user",
            target_repos=["test-user/test-repo"],
            backfill_days=30,
            fetch_commit_details=True,
            max_commit_detail_requests_per_repo=10,
        ),
        duckdb=DuckDBConfig(r2=r2),
    )


def _seed_duplicate_commits(memory_s3) -> None:
    """同一 commit_event_id のイベントを2つのParquetファイルとして保存する。"""
    storage = GitHubWorklogStorage(
        endpoint_url=memory_s3.endpoint_url,
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        bucket_name="test-bucket",
    )

    rows = [
        {
            "commit_event_id": "test-user/test-repo:abc123",
            "source": "github",
            "owner": "test-user",
            "repo": "test-repo",
            "repo_full_name": "test-user/test-repo",
            "sha": "abc123",
            "message": "Test commit",
            "committed_at_utc": "2026-04-01T00:00:00Z",
            "changed_files_count": 1,
            "additions": 10,
            "deletions": 5,
            "ingested_at_utc": "2026-04-01T00:00:00Z",
        },
    ]
    table = pa.Table.from_pandas(pd.DataFrame(rows))

    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)

    storage.s3.put_object(
        Bucket="test-bucket",
        Key="events/github/commits/year=2026/month=04/file-a.parquet",
        Body=buf.read(),
    )
    buf.seek(0)
    storage.s3.put_object(
        Bucket="test-bucket",
        Key="events/github/commits/year=2026/month=04/file-b.parquet",
        Body=buf.read(),
    )


def test_compact_deduplicates_commits():
    """Compaction が同一 commit_event_id のレコードを重複排除する。"""
    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)

        _seed_duplicate_commits(memory_s3)

        result = run_github_compact(config=config)

        assert result["operation"] == "compact"
        assert len(result["compacted_keys"]) > 0

        compacted_key = result["compacted_keys"][0]
        storage = GitHubWorklogStorage(
            endpoint_url=memory_s3.endpoint_url,
            access_key_id="test-access-key",
            secret_access_key="test-secret-key",
            bucket_name="test-bucket",
        )
        resp = storage.s3.get_object(Bucket="test-bucket", Key=compacted_key)
        compacted_table = pq.read_table(io.BytesIO(resp["Body"].read()))
        assert len(compacted_table) == 1, (
            f"Expected 1 deduplicated row, got {len(compacted_table)}"
        )


def test_compact_skips_empty_month():
    """データがない月の compaction はスキップされる。"""
    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)

        result = run_github_compact(config=config)

        assert len(result["compacted_keys"]) == 0
        assert len(result["skipped_targets"]) > 0
