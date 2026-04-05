"""GitHub ingest パイプラインのインテグレーションテスト。

MemoryS3 + responses モックを使用し、Collector → Transform → S3 Storage の
全データフローを検証する。
"""

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
from pipelines.tests.e2e.test_browser_history_ingest import (
    _MemoryS3Server,
)
from pipelines.tests.fixtures.github_responses import (
    MOCK_COMMIT_DETAIL_RESPONSE,
    MOCK_PR_REVIEWS_RESPONSE,
    MOCK_PULL_REQUEST_RESPONSE,
    MOCK_REPOSITORY_COMMITS_RESPONSE,
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


def _mock_github_api(
    pr_count: int = 1,
    commit_count: int = 1,
    pr_data: list | None = None,
    commit_data: list | None = None,
):
    """GitHub API の必要エンドポイントをモックする。"""
    base = "https://api.github.com"

    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo",
        json=MOCK_REPOSITORY_RESPONSE,
        status=200,
    )

    # PRs
    if pr_data is not None:
        pr_list = pr_data
    elif pr_count > 0:
        pr_list = [MOCK_PULL_REQUEST_RESPONSE] * pr_count
    else:
        pr_list = []
    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo/pulls",
        json=pr_list,
        status=200,
    )

    # PR reviews
    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo/pulls/1/reviews",
        json=MOCK_PR_REVIEWS_RESPONSE,
        status=200,
    )

    # Commits
    if commit_data is not None:
        commits = commit_data
    elif commit_count > 0:
        commits = MOCK_REPOSITORY_COMMITS_RESPONSE[:commit_count]
    else:
        commits = []
    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo/commits",
        json=commits,
        status=200,
    )

    # Commit detail
    responses.add(
        responses.GET,
        f"{base}/repos/test-user/test-repo/commits/abc123def456",
        json=MOCK_COMMIT_DETAIL_RESPONSE,
        status=200,
    )


@responses.activate
def test_ingest_saves_raw_events_and_state():
    """Ingest が raw JSON, events Parquet, ingest state を S3 に保存する。"""
    current_month = "2026-04"
    pr = {
        **MOCK_PULL_REQUEST_RESPONSE,
        "created_at": f"{current_month}-01T00:00:00Z",
        "updated_at": f"{current_month}-01T01:00:00Z",
        "head": {
            "ref": "feature-branch",
            "repo": {
                "full_name": "test-user/test-repo",
                "owner": {"login": "test-user"},
            },
        },
    }
    commit = {
        "sha": "abc123def456",
        "commit": {
            "author": {
                "name": "Test User",
                "email": "test@example.com",
                "date": f"{current_month}-01T00:00:00Z",
            },
            "message": "Direct commit to main",
        },
        "author": {"login": "test-user", "id": 12345},
    }

    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)
        _mock_github_api(pr_data=[pr], commit_data=[commit])

        result = run_github_ingest(config=config)

        assert result["status"] == "succeeded"
        object_keys = {key for _, key in memory_s3.objects}

        assert any(k.startswith("raw/github/pull_requests/") for k in object_keys), (
            "raw PR data not found"
        )

        assert any(k.startswith("raw/github/commits/") for k in object_keys), (
            "raw commit data not found"
        )

        assert any(
            k.startswith("events/github/pull_requests/year=") for k in object_keys
        ), "PR events not found"

        assert any(k.startswith("events/github/commits/year=") for k in object_keys), (
            "commit events not found"
        )

        assert any(
            "state/github_worklog_ingest_state.json" in k for k in object_keys
        ), "ingest state not found"


@responses.activate
def test_ingest_no_data_returns_early():
    """PR・コミット両方なしの場合、保存処理を実行せずに早期リターンする。"""
    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)
        _mock_github_api(pr_count=0, commit_count=0)

        result = run_github_ingest(config=config)

        assert result["status"] == "succeeded"
        object_keys = {key for _, key in memory_s3.objects}
        # リポジトリ情報とstateのみ保存される
        assert not any(k.startswith("raw/github/") for k in object_keys), (
            "raw data should not be saved when no data"
        )
        assert not any(k.startswith("events/github/") for k in object_keys), (
            "events should not be saved when no data"
        )
