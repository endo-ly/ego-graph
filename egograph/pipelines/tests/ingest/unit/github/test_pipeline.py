from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from pydantic import SecretStr

from pipelines.sources.common.config import (
    Config,
    DuckDBConfig,
    GitHubWorklogConfig,
    R2Config,
)
from pipelines.sources.github.ingest_pipeline import _resolve_since_iso, run_pipeline


def _build_config() -> Config:
    return Config(
        log_level="INFO",
        github_worklog=GitHubWorklogConfig(
            token=SecretStr("token"),
            github_login="test-user",
            target_repos=["test-user/test-repo"],
            backfill_days=30,
            fetch_commit_details=True,
            max_commit_detail_requests_per_repo=200,
        ),
        duckdb=DuckDBConfig(
            db_path=":memory:",
            r2=R2Config(
                endpoint_url="https://example.r2.cloudflarestorage.com",
                access_key_id="access",
                secret_access_key=SecretStr("secret"),
                bucket_name="bucket",
            ),
        ),
    )


def _build_personal_repo() -> dict:
    return {
        "id": 1,
        "owner": {"login": "test-user"},
        "name": "test-repo",
        "full_name": "test-user/test-repo",
    }


def _build_pr() -> dict:
    return {
        "id": 10,
        "number": 1,
        "state": "open",
        "title": "PR",
        "head": {
            "ref": "feature",
            "repo": {
                "owner": {"login": "test-user"},
                "name": "test-repo",
                "full_name": "test-user/test-repo",
            },
        },
        "base": {"ref": "main"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "comments": 0,
        "review_comments": 0,
        "commits": 1,
        "additions": 1,
        "deletions": 1,
        "changed_files": 1,
        "labels": [],
        "merged_at": None,
    }


def _build_commit() -> dict:
    return {
        "sha": "abc",
        "commit": {
            "message": "msg",
            "author": {"date": "2026-01-03T00:00:00Z"},
        },
    }


def _build_commit_detail() -> dict:
    return {
        "sha": "abc",
        "commit": {
            "message": "msg",
            "author": {"date": "2026-01-03T00:00:00Z"},
        },
        "stats": {"additions": 2, "deletions": 1, "total": 3},
        "files": [{"filename": "a.py"}],
    }


def test_resolve_since_iso_uses_cursor_if_exists():
    state = {"cursor_utc": "2026-01-01T00:00:00+00:00"}
    assert _resolve_since_iso(state, backfill_days=10) == "2026-01-01T00:00:00+00:00"


def test_resolve_since_iso_uses_backfill_if_no_cursor():
    since = _resolve_since_iso(None, backfill_days=7)
    parsed = datetime.fromisoformat(since)
    now = datetime.now(timezone.utc)
    delta = now - parsed
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


def test_run_pipeline_updates_state_on_enrichment_api_failure(monkeypatch):
    config = _build_config()

    storage = MagicMock()
    storage.get_ingest_state.return_value = {"cursor_utc": "2026-01-01T00:00:00+00:00"}
    storage.save_repo_master.return_value = "repo.parquet"
    storage.save_pr_events_parquet_with_stats.return_value = {
        "fetched": 1,
        "new": 1,
        "duplicates": 0,
        "failed": 0,
    }
    storage.save_raw_prs.return_value = "pr.json"
    storage.save_raw_commits.return_value = "commits.json"
    storage.save_commits_parquet_with_stats.return_value = {
        "fetched": 1,
        "new": 1,
        "duplicates": 0,
        "failed": 0,
    }

    collector = MagicMock()
    collector.get_repository.return_value = _build_personal_repo()
    collector.get_pull_requests.return_value = [_build_pr()]
    collector.get_pr_reviews.side_effect = RuntimeError("api failed")
    collector.get_repository_commits.return_value = [_build_commit()]
    collector.get_commit_detail.return_value = _build_commit_detail()

    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogStorage",
        lambda **_: storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogCollector",
        lambda **_: collector,
    )

    run_pipeline(config)

    storage.save_ingest_state.assert_called_once()


def test_run_pipeline_does_not_update_state_on_fatal_repo_failure(monkeypatch):
    config = _build_config()

    storage = MagicMock()
    storage.get_ingest_state.return_value = {"cursor_utc": "2026-01-01T00:00:00+00:00"}

    collector = MagicMock()
    collector.get_repository.side_effect = RuntimeError("fatal api failure")

    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogStorage",
        lambda **_: storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogCollector",
        lambda **_: collector,
    )

    run_pipeline(config)

    storage.save_ingest_state.assert_not_called()


def test_run_pipeline_uses_cursor_and_updates_state_on_success(monkeypatch):
    config = _build_config()

    storage = MagicMock()
    storage.get_ingest_state.return_value = {"cursor_utc": "2026-01-01T00:00:00+00:00"}
    storage.save_repo_master.return_value = "repo.parquet"
    storage.save_pr_events_parquet_with_stats.return_value = {
        "fetched": 1,
        "new": 1,
        "duplicates": 0,
        "failed": 0,
    }
    storage.save_raw_prs.return_value = "pr.json"
    storage.save_raw_commits.return_value = "commits.json"
    storage.save_commits_parquet_with_stats.return_value = {
        "fetched": 1,
        "new": 1,
        "duplicates": 0,
        "failed": 0,
    }

    collector = MagicMock()
    collector.get_repository.return_value = _build_personal_repo()
    collector.get_pull_requests.return_value = [_build_pr()]
    collector.get_pr_reviews.return_value = []
    collector.get_repository_commits.return_value = [_build_commit()]
    collector.get_commit_detail.return_value = _build_commit_detail()

    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogStorage",
        lambda **_: storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogCollector",
        lambda **_: collector,
    )

    run_pipeline(config)

    collector.get_pull_requests.assert_called_once_with(
        "test-user",
        "test-repo",
        since="2026-01-01T00:00:00+00:00",
    )
    collector.get_repository_commits.assert_called_once_with(
        "test-user",
        "test-repo",
        since="2026-01-01T00:00:00+00:00",
    )
    storage.save_ingest_state.assert_called_once()
    state_arg = storage.save_ingest_state.call_args[0][0]
    assert state_arg["cursor_utc"] == "2026-01-03T00:00:00+00:00"


def test_run_pipeline_skips_commit_detail_when_disabled(monkeypatch):
    config = _build_config()
    config.github_worklog.fetch_commit_details = False

    storage = MagicMock()
    storage.get_ingest_state.return_value = {"cursor_utc": "2026-01-01T00:00:00+00:00"}
    storage.save_repo_master.return_value = "repo.parquet"
    storage.save_pr_events_parquet_with_stats.return_value = {
        "fetched": 1,
        "new": 1,
        "duplicates": 0,
        "failed": 0,
    }
    storage.save_raw_prs.return_value = "pr.json"
    storage.save_raw_commits.return_value = "commits.json"
    storage.save_commits_parquet_with_stats.return_value = {
        "fetched": 1,
        "new": 1,
        "duplicates": 0,
        "failed": 0,
    }

    collector = MagicMock()
    collector.get_repository.return_value = _build_personal_repo()
    collector.get_pull_requests.return_value = [_build_pr()]
    collector.get_pr_reviews.return_value = []
    collector.get_repository_commits.return_value = [_build_commit()]

    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogStorage",
        lambda **_: storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogCollector",
        lambda **_: collector,
    )

    run_pipeline(config)

    collector.get_commit_detail.assert_not_called()
