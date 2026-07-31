from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from pipelines.sources.common.config import (
    Config,
    DuckDBConfig,
    GitHubWorklogConfig,
    R2Config,
)
from pipelines.sources.github.ingest_pipeline import (
    _migrate_state,
    _resolve_since_iso,
    run_pipeline,
)
from pydantic import SecretStr


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


def _configure_successful_pipeline_mocks(
    storage: MagicMock,
    collector: MagicMock,
    state: dict | None = None,
) -> None:
    """単一リポジトリの正常系mockを構築する。"""
    storage.get_ingest_state.return_value = state or {
        "github_login": "test-user",
        "repos": {
            "test-user/test-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
        },
    }
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

    collector.get_repository.return_value = _build_personal_repo()
    collector.get_pull_requests.return_value = [_build_pr()]
    collector.get_pr_reviews.return_value = []
    collector.get_repository_commits.return_value = [_build_commit()]
    collector.get_commit_detail.return_value = _build_commit_detail()


def _patch_pipeline_dependencies(monkeypatch, storage, collector):
    """run_pipelineの外部依存をテストdoubleへ差し替える。"""
    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogStorage",
        lambda **_: storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogCollector",
        lambda **_: collector,
    )


class TestMigrateState:
    def test_migrate_none_state(self):
        result = _migrate_state(None)
        assert result == {"github_login": None, "repos": {}}

    def test_migrate_new_format_unchanged(self):
        state = {
            "github_login": "test-user",
            "repos": {"test-user/repo": {"cursor_utc": "2026-01-01T00:00:00Z"}},
        }
        assert _migrate_state(state) is state

    def test_migrate_legacy_cursor_utc(self):
        state = {
            "cursor_utc": "2026-01-01T00:00:00Z",
            "total_repos": 1,
        }
        result = _migrate_state(state)
        assert result == {
            "github_login": None,
            "global_cursor_utc": "2026-01-01T00:00:00Z",
            "repos": {},
        }

    def test_migrate_legacy_last_ingested_at(self):
        state = {
            "last_ingested_at": "2026-01-01T00:00:00Z",
        }
        result = _migrate_state(state)
        assert result == {
            "github_login": None,
            "global_cursor_utc": "2026-01-01T00:00:00Z",
            "repos": {},
        }


class TestResolveSinceIso:
    def test_uses_repo_cursor(self):
        state = {
            "repos": {
                "test-user/test-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
            },
        }
        assert (
            _resolve_since_iso("test-user/test-repo", state, backfill_days=10)
            == "2026-01-01T00:00:00+00:00"
        )

    def test_uses_global_cursor_when_no_repo_cursor(self):
        state = {
            "global_cursor_utc": "2026-01-01T00:00:00+00:00",
            "repos": {},
        }
        assert (
            _resolve_since_iso("test-user/test-repo", state, backfill_days=10)
            == "2026-01-01T00:00:00+00:00"
        )

    def test_uses_backfill_when_no_cursor(self):
        state = {"repos": {}}
        since = _resolve_since_iso("test-user/test-repo", state, backfill_days=7)
        parsed = datetime.fromisoformat(since)
        now = datetime.now(timezone.utc)
        delta = now - parsed
        assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


def test_run_pipeline_updates_state_on_enrichment_api_failure(monkeypatch):
    config = _build_config()

    storage = MagicMock()
    storage.get_ingest_state.return_value = {
        "github_login": "test-user",
        "repos": {
            "test-user/test-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
        },
    }
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
    storage.get_ingest_state.return_value = {
        "github_login": "test-user",
        "repos": {
            "test-user/test-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
        },
    }

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

    with pytest.raises(RuntimeError, match="GitHub ingest failed"):
        run_pipeline(config)

    # 致命的エラー時は state は保存されるが、失敗リポジトリのcursorは更新されない
    storage.save_ingest_state.assert_called_once()
    state_arg = storage.save_ingest_state.call_args[0][0]
    # 失敗リポジトリは旧cursorを維持
    assert state_arg["repos"]["test-user/test-repo"]["cursor_utc"] == (
        "2026-01-01T00:00:00+00:00"
    )


@pytest.mark.parametrize(
    "failure_kind",
    ["repo_master", "pr_events", "raw_prs", "raw_commits", "commit_events"],
)
def test_run_pipeline_does_not_advance_cursor_when_required_save_fails(
    monkeypatch,
    failure_kind,
):
    """必須データの保存失敗時は既存cursorを維持する。"""
    config = _build_config()
    storage = MagicMock()
    collector = MagicMock()
    _configure_successful_pipeline_mocks(storage, collector)

    if failure_kind == "repo_master":
        storage.save_repo_master.return_value = None
    elif failure_kind == "pr_events":
        storage.save_pr_events_parquet_with_stats.return_value = {
            "fetched": 1,
            "new": 0,
            "duplicates": 0,
            "failed": 1,
        }
    elif failure_kind == "raw_prs":
        storage.save_raw_prs.return_value = None
    elif failure_kind == "raw_commits":
        storage.save_raw_commits.return_value = None
    else:
        storage.save_commits_parquet_with_stats.return_value = {
            "fetched": 1,
            "new": 0,
            "duplicates": 0,
            "failed": 1,
        }

    _patch_pipeline_dependencies(monkeypatch, storage, collector)

    with pytest.raises(RuntimeError, match="GitHub ingest failed"):
        run_pipeline(config)

    storage.save_ingest_state.assert_called_once()
    state_arg = storage.save_ingest_state.call_args[0][0]
    assert state_arg["repos"]["test-user/test-repo"]["cursor_utc"] == (
        "2026-01-01T00:00:00+00:00"
    )


def test_run_pipeline_does_not_add_cursor_for_failed_new_repo(monkeypatch):
    """新規リポジトリの必須保存失敗時はcursorをstateへ追加しない。"""
    config = _build_config()
    storage = MagicMock()
    collector = MagicMock()
    _configure_successful_pipeline_mocks(
        storage,
        collector,
        state={"github_login": "test-user", "repos": {}},
    )
    storage.save_repo_master.return_value = None
    _patch_pipeline_dependencies(monkeypatch, storage, collector)

    with pytest.raises(RuntimeError, match="GitHub ingest failed"):
        run_pipeline(config)

    state_arg = storage.save_ingest_state.call_args[0][0]
    assert "test-user/test-repo" not in state_arg["repos"]


def test_run_pipeline_shared_commit_failure_blocks_all_contributing_repos(monkeypatch):
    """共有月partitionの保存失敗時は寄与した全repoのcursorを止める。"""
    config = _build_config()
    config.github_worklog.target_repos = [
        "test-user/first-repo",
        "test-user/second-repo",
    ]
    storage = MagicMock()
    collector = MagicMock()
    _configure_successful_pipeline_mocks(
        storage,
        collector,
        state={
            "github_login": "test-user",
            "repos": {
                "test-user/first-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
                "test-user/second-repo": {"cursor_utc": "2026-01-02T00:00:00+00:00"},
            },
        },
    )
    storage.save_commits_parquet_with_stats.return_value = {
        "fetched": 2,
        "new": 0,
        "duplicates": 0,
        "failed": 2,
    }
    _patch_pipeline_dependencies(monkeypatch, storage, collector)

    with pytest.raises(RuntimeError, match="first-repo.*second-repo"):
        run_pipeline(config)

    state_arg = storage.save_ingest_state.call_args[0][0]
    assert state_arg["repos"] == {
        "test-user/first-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
        "test-user/second-repo": {"cursor_utc": "2026-01-02T00:00:00+00:00"},
    }


def test_run_pipeline_saves_state_when_shared_commit_save_raises(monkeypatch):
    """共有partitionの保存例外時もstate保存後に失敗を通知する。"""
    config = _build_config()
    storage = MagicMock()
    collector = MagicMock()
    _configure_successful_pipeline_mocks(storage, collector)
    storage.save_commits_parquet_with_stats.side_effect = RuntimeError(
        "commit parquet write failed"
    )
    _patch_pipeline_dependencies(monkeypatch, storage, collector)

    with pytest.raises(RuntimeError, match="GitHub ingest failed"):
        run_pipeline(config)

    storage.save_ingest_state.assert_called_once()
    state_arg = storage.save_ingest_state.call_args[0][0]
    assert state_arg["repos"]["test-user/test-repo"]["cursor_utc"] == (
        "2026-01-01T00:00:00+00:00"
    )


def test_run_pipeline_updates_only_successful_repo_cursor(monkeypatch):
    """複数repoの一部失敗時は成功repoだけcursorを更新する。"""
    config = _build_config()
    config.github_worklog.target_repos = [
        "test-user/first-repo",
        "test-user/second-repo",
    ]
    storage = MagicMock()
    collector = MagicMock()
    _configure_successful_pipeline_mocks(
        storage,
        collector,
        state={
            "github_login": "test-user",
            "repos": {
                "test-user/first-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
                "test-user/second-repo": {"cursor_utc": "2026-01-02T00:00:00+00:00"},
            },
        },
    )
    storage.save_repo_master.side_effect = ["repo.parquet", None]
    _patch_pipeline_dependencies(monkeypatch, storage, collector)

    with pytest.raises(RuntimeError, match="second-repo"):
        run_pipeline(config)

    state_arg = storage.save_ingest_state.call_args[0][0]
    assert state_arg["repos"]["test-user/first-repo"]["cursor_utc"] == (
        "2026-01-03T00:00:00+00:00"
    )
    assert state_arg["repos"]["test-user/second-repo"]["cursor_utc"] == (
        "2026-01-02T00:00:00+00:00"
    )


def test_run_pipeline_state_save_failure_is_not_success(monkeypatch):
    """state保存失敗時はstate保存を一度試行し、成功扱いにしない。"""
    config = _build_config()
    storage = MagicMock()
    collector = MagicMock()
    _configure_successful_pipeline_mocks(storage, collector)
    storage.save_ingest_state.side_effect = RuntimeError("state write failed")
    _patch_pipeline_dependencies(monkeypatch, storage, collector)

    with pytest.raises(RuntimeError, match="Failed to save GitHub ingest state"):
        run_pipeline(config)

    storage.save_ingest_state.assert_called_once()


def test_run_pipeline_uses_cursor_and_updates_state_on_success(monkeypatch):
    config = _build_config()

    storage = MagicMock()
    storage.get_ingest_state.return_value = {
        "github_login": "test-user",
        "repos": {
            "test-user/test-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
        },
    }
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
    assert state_arg["github_login"] == "test-user"
    assert state_arg["repos"]["test-user/test-repo"]["cursor_utc"] == (
        "2026-01-03T00:00:00+00:00"
    )


def test_run_pipeline_skips_commit_detail_when_disabled(monkeypatch):
    config = _build_config()
    config.github_worklog.fetch_commit_details = False

    storage = MagicMock()
    storage.get_ingest_state.return_value = {
        "github_login": "test-user",
        "repos": {
            "test-user/test-repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
        },
    }
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


def test_run_pipeline_login_change_resets_state(monkeypatch):
    """GitHub login が変更された場合、stateがリセットされる。"""
    config = _build_config()

    storage = MagicMock()
    # 古いloginのstate
    storage.get_ingest_state.return_value = {
        "github_login": "old-user",
        "repos": {
            "old-user/repo": {"cursor_utc": "2026-01-01T00:00:00+00:00"},
        },
    }
    storage.save_repo_master.return_value = "repo.parquet"
    storage.save_pr_events_parquet_with_stats.return_value = {
        "fetched": 0,
        "new": 0,
        "duplicates": 0,
        "failed": 0,
    }
    storage.save_raw_prs.return_value = "pr.json"
    storage.save_raw_commits.return_value = "commits.json"
    storage.save_commits_parquet_with_stats.return_value = {
        "fetched": 0,
        "new": 0,
        "duplicates": 0,
        "failed": 0,
    }

    collector = MagicMock()
    collector.get_repository.return_value = _build_personal_repo()
    collector.get_pull_requests.return_value = []
    collector.get_repository_commits.return_value = []

    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogStorage",
        lambda **_: storage,
    )
    monkeypatch.setattr(
        "pipelines.sources.github.ingest_pipeline.GitHubWorklogCollector",
        lambda **_: collector,
    )

    run_pipeline(config)

    state_arg = storage.save_ingest_state.call_args[0][0]
    assert state_arg["github_login"] == "test-user"
    # 古いrepoのcursorは残らず、新しいrepoのcursorが保存される
    assert "old-user/repo" not in state_arg["repos"]
    assert "test-user/test-repo" in state_arg["repos"]
