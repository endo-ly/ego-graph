"""GitHub 補完 (enrichment) のインテグレーションテスト。

PR review 件数補完と commit detail 補完のフローを検証する。
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
    MOCK_PULL_REQUEST_RESPONSE,
    MOCK_REPOSITORY_RESPONSE,
)


def _build_config(memory_s3, **kwargs) -> Config:
    """GitHub pipeline 用の設定を構築する。"""
    r2 = R2Config(
        endpoint_url=memory_s3.endpoint_url,
        access_key_id="test-access-key",
        secret_access_key=SecretStr("test-secret-key"),
        bucket_name="test-bucket",
    )
    github_kwargs = {
        "token": SecretStr("test-github-token"),
        "github_login": "test-user",
        "target_repos": ["test-user/test-repo"],
        "backfill_days": 30,
        "fetch_commit_details": True,
        "max_commit_detail_requests_per_repo": 10,
    }
    github_kwargs.update(kwargs)
    return Config(
        github_worklog=GitHubWorklogConfig(**github_kwargs),
        duckdb=DuckDBConfig(r2=r2),
    )


def _current_month_pr():
    """現在月の日付で PR モックデータを生成する。"""
    return {
        **MOCK_PULL_REQUEST_RESPONSE,
        "created_at": "2026-04-01T00:00:00Z",
        "updated_at": "2026-04-01T01:00:00Z",
        "head": {
            "ref": "feature-branch",
            "repo": {
                "full_name": "test-user/test-repo",
                "owner": {"login": "test-user"},
            },
        },
    }


def _current_month_commit():
    """現在月の日付でコミットモックデータを生成する。"""
    return {
        "sha": "abc123def456",
        "commit": {
            "author": {
                "name": "Test User",
                "email": "test@example.com",
                "date": "2026-04-01T00:00:00Z",
            },
            "message": "Test commit",
        },
        "author": {"login": "test-user", "id": 12345},
    }


@responses.activate
def test_enrichment_fetches_pr_reviews():
    """PR ごとに review 件数が補完される。"""
    base = "https://api.github.com"
    review_calls = []

    def capture_reviews(request):
        review_calls.append(request.url)
        return (200, {}, '[{"id": 1, "state": "APPROVED"}]')

    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)

        responses.add(
            responses.GET,
            f"{base}/repos/test-user/test-repo",
            json=MOCK_REPOSITORY_RESPONSE,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{base}/repos/test-user/test-repo/pulls",
            json=[_current_month_pr()],
            status=200,
        )
        responses.add_callback(
            responses.GET,
            f"{base}/repos/test-user/test-repo/pulls/1/reviews",
            callback=capture_reviews,
        )
        responses.add(
            responses.GET,
            f"{base}/repos/test-user/test-repo/commits",
            json=[],
            status=200,
        )

        result = run_github_ingest(config=config)
        assert result["status"] == "succeeded"

        # reviews API が呼ばれている
        assert len(review_calls) == 1


@responses.activate
def test_enrichment_skips_commit_detail_when_disabled():
    """fetch_commit_details=False の場合、commit detail API は呼ばれない。"""
    base = "https://api.github.com"
    detail_calls = []

    def capture_detail(request):
        detail_calls.append(request.url)
        return (200, {}, "{}")

    with _MemoryS3Server() as memory_s3:
        config = _build_config(
            memory_s3,
            fetch_commit_details=False,
        )

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
            json=[_current_month_commit()],
            status=200,
        )
        responses.add_callback(
            responses.GET,
            f"{base}/repos/test-user/test-repo/commits/abc123def456",
            callback=capture_detail,
        )

        result = run_github_ingest(config=config)
        assert result["status"] == "succeeded"

        # commit detail API は呼ばれない
        assert len(detail_calls) == 0
