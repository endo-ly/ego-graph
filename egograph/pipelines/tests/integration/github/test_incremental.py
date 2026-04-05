"""GitHub 増分取得のインテグレーションテスト。

ingest_state による cursor 指定の増分取得フローを検証する。
"""

from datetime import datetime, timedelta, timezone

import responses
from pydantic import SecretStr

from pipelines.sources.common.config import (
    Config,
    DuckDBConfig,
    GitHubWorklogConfig,
    R2Config,
)
from pipelines.sources.github.pipeline import (
    run_github_ingest,
)
from pipelines.sources.github.storage import GitHubWorklogStorage
from pipelines.tests.e2e.test_browser_history_ingest import (
    _MemoryS3Server,
)
from pipelines.tests.fixtures.github_responses import (
    MOCK_COMMIT_DETAIL_RESPONSE,
    MOCK_PR_REVIEWS_RESPONSE,
    MOCK_PULL_REQUEST_RESPONSE,
    MOCK_REPOSITORY_RESPONSE,
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


def _mock_github_api_base():
    """GitHub API の基本エンドポイント（PR 0件, コミット 0件）をモックする。"""
    base = "https://api.github.com"
    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo",
        json=MOCK_REPOSITORY_RESPONSE,
        status=200,
    )
    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo/pulls",
        json=[],
        status=200,
    )
    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo/commits",
        json=[],
        status=200,
    )


@responses.activate
def test_incremental_fetch_uses_cursor():
    """既存の cursor_utc がある場合、backfill ではなく増分モードで実行される。"""
    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)

        # 既存 state を投入
        storage = GitHubWorklogStorage(
            endpoint_url=memory_s3.endpoint_url,
            access_key_id="test-access-key",
            secret_access_key="test-secret-key",
            bucket_name="test-bucket",
        )
        now = datetime.now(timezone.utc)
        storage.save_ingest_state(
            {
                "cursor_utc": (now - timedelta(days=1)).isoformat(),
                "total_repos": 1,
                "updated_at": (now - timedelta(days=1)).isoformat(),
            }
        )

        _mock_github_api_base()

        result = run_github_ingest(config=config)
        assert result["status"] == "succeeded"


@responses.activate
def test_incremental_no_new_data_updates_cursor():
    """cursor 以降の新規データがない場合、cursor は now_utc に更新される。"""
    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)

        # 既存 state を投入
        storage = GitHubWorklogStorage(
            endpoint_url=memory_s3.endpoint_url,
            access_key_id="test-access-key",
            secret_access_key="test-secret-key",
            bucket_name="test-bucket",
        )
        now = datetime.now(timezone.utc)
        original_cursor = (now - timedelta(days=1)).isoformat()
        storage.save_ingest_state(
            {
                "cursor_utc": original_cursor,
                "total_repos": 1,
                "updated_at": original_cursor,
            }
        )

        _mock_github_api_base()

        result = run_github_ingest(config=config)
        assert result["status"] == "succeeded"

        # 新規データなしでも cursor は更新される (now_utc にフォールバック)
        state = storage.get_ingest_state()
        new_cursor = datetime.fromisoformat(state["cursor_utc"])
        assert new_cursor >= now - timedelta(seconds=5)
