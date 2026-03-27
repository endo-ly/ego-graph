"""Integration tests that read actual compacted parquet files."""

from datetime import date
from pathlib import Path

import pandas as pd
from pydantic import SecretStr

from backend.config import R2Config
from backend.infrastructure.database.browser_history_queries import (
    BrowserHistoryQueryParams,
    get_page_views,
    get_top_domains,
)
from backend.infrastructure.database.github_queries import (
    GitHubQueryParams,
    get_activity_stats,
    get_commits,
    get_pull_requests,
    get_repo_summary_stats,
)
from backend.infrastructure.database.queries import (
    QueryParams,
    get_listening_stats,
    get_top_tracks,
)


def _build_config(local_root: Path) -> R2Config:
    return R2Config.model_construct(
        endpoint_url="https://test.r2.cloudflarestorage.com",
        access_key_id="test_key",
        secret_access_key=SecretStr("test_secret"),
        bucket_name="test-bucket",
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
        local_parquet_root=str(local_root),
    )


def test_spotify_queries_read_local_compacted_parquet(duckdb_conn, tmp_path):
    local_root = tmp_path / "mirror"
    spotify_dir = (
        local_root
        / "compacted"
        / "events"
        / "spotify"
        / "plays"
        / "year=2024"
        / "month=01"
    )
    spotify_dir.mkdir(parents=True)

    pd.DataFrame(
        {
            "play_id": ["play_1", "play_2", "play_3"],
            "played_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-01 11:00:00", "2024-01-02 10:00:00"]
            ),
            "track_id": ["track_1", "track_1", "track_2"],
            "track_name": ["Song A", "Song A", "Song B"],
            "artist_names": [["Artist X"], ["Artist X"], ["Artist Y"]],
            "ms_played": [180000, 180000, 240000],
        }
    ).to_parquet(spotify_dir / "data.parquet")

    params = QueryParams(
        conn=duckdb_conn,
        bucket="test-bucket",
        events_path="events/",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        r2_config=_build_config(local_root),
    )

    top_tracks = get_top_tracks(params, limit=5)
    listening_stats = get_listening_stats(params, granularity="day")

    assert top_tracks[0]["track_name"] == "Song A"
    assert top_tracks[0]["play_count"] == 2
    assert listening_stats[0]["period"] == "2024-01-01"


def test_github_queries_read_local_compacted_parquet(duckdb_conn, tmp_path):
    local_root = tmp_path / "mirror"
    pr_dir = (
        local_root
        / "compacted"
        / "events"
        / "github"
        / "pull_requests"
        / "year=2024"
        / "month=01"
    )
    commit_dir = (
        local_root
        / "compacted"
        / "events"
        / "github"
        / "commits"
        / "year=2024"
        / "month=01"
    )
    pr_dir.mkdir(parents=True)
    commit_dir.mkdir(parents=True)

    pd.DataFrame(
        {
            "pr_event_id": ["pr_event_1", "pr_event_2"],
            "pr_key": ["pr_1", "pr_1"],
            "owner": ["test_owner", "test_owner"],
            "repo": ["test_repo", "test_repo"],
            "repo_full_name": ["test_owner/test_repo", "test_owner/test_repo"],
            "pr_number": [1, 1],
            "action": ["opened", "merged"],
            "state": ["open", "closed"],
            "is_merged": [False, True],
            "title": ["PR 1", "PR 1"],
            "labels": [["bug"], ["bug"]],
            "created_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-01 10:00:00"]
            ),
            "updated_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-02 10:00:00"]
            ),
            "closed_at_utc": pd.to_datetime([None, "2024-01-02 10:00:00"]),
            "merged_at_utc": pd.to_datetime([None, "2024-01-02 10:00:00"]),
            "additions": [10, 20],
            "deletions": [1, 2],
            "changed_files_count": [1, 2],
            "reviews_count": [0, 1],
            "commits_count": [1, 2],
        }
    ).to_parquet(pr_dir / "data.parquet")

    pd.DataFrame(
        {
            "commit_event_id": ["commit_1", "commit_2"],
            "owner": ["test_owner", "test_owner"],
            "repo": ["test_repo", "test_repo"],
            "repo_full_name": ["test_owner/test_repo", "test_owner/test_repo"],
            "sha": ["abc123", "def456"],
            "message": ["Initial", "Follow-up"],
            "committed_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-02 12:00:00"]
            ),
            "changed_files_count": [1, 2],
            "additions": [5, 7],
            "deletions": [1, 3],
        }
    ).to_parquet(commit_dir / "data.parquet")

    params = GitHubQueryParams(
        conn=duckdb_conn,
        bucket="test-bucket",
        events_path="events/",
        master_path="master/",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        r2_config=_build_config(local_root),
    )

    prs = get_pull_requests(params)
    commits = get_commits(params)
    activity = get_activity_stats(params, granularity="day")
    summary = get_repo_summary_stats(params)

    assert len(prs) == 2
    assert len(commits) == 2
    assert activity[0]["period"] == "2024-01-01"
    assert summary[0]["owner"] == "test_owner"


def test_browser_history_queries_read_local_compacted_parquet(duckdb_conn, tmp_path):
    local_root = tmp_path / "mirror"
    browser_dir = (
        local_root
        / "compacted"
        / "events"
        / "browser_history"
        / "page_views"
        / "year=2026"
        / "month=03"
    )
    browser_dir.mkdir(parents=True)

    pd.DataFrame(
        {
            "page_view_id": ["pv_1", "pv_2", "pv_3"],
            "started_at_utc": pd.to_datetime(
                [
                    "2026-03-20 10:00:00",
                    "2026-03-20 11:00:00",
                    "2026-03-21 09:00:00",
                ]
            ),
            "ended_at_utc": pd.to_datetime(
                [
                    "2026-03-20 10:02:00",
                    "2026-03-20 11:03:00",
                    "2026-03-21 09:01:00",
                ]
            ),
            "url": [
                "https://github.com/openai/openai-python",
                "https://github.com/openai/openai-cookbook",
                "https://news.ycombinator.com/item?id=1",
            ],
            "title": ["Repo 1", "Repo 2", "HN"],
            "browser": ["edge", "edge", "chrome"],
            "profile": ["Default", "Default", "Work"],
            "transition": ["link", "link", "typed"],
            "visit_span_count": [1, 1, 1],
        }
    ).to_parquet(browser_dir / "data.parquet")

    params = BrowserHistoryQueryParams(
        conn=duckdb_conn,
        bucket="test-bucket",
        events_path="events/",
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 21),
        r2_config=_build_config(local_root),
    )

    page_views = get_page_views(params, browser="edge", profile="Default", limit=10)
    top_domains = get_top_domains(params, limit=10)

    assert [row["page_view_id"] for row in page_views] == ["pv_2", "pv_1"]
    assert top_domains[0]["domain"] == "github.com"
    assert top_domains[0]["page_view_count"] == 2
