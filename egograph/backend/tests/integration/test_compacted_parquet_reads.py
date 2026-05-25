"""Integration tests that read actual compacted parquet files."""

from datetime import date, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import SecretStr

from backend.config import R2Config
from backend.infrastructure.database.browser_history_queries import (
    get_page_views,
    get_top_domains,
)
from backend.infrastructure.database.github_queries import (
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
from backend.validators import to_utc_range


def _utc_range(start_date: date, end_date: date):
    return to_utc_range(start_date, end_date, timezone.utc)


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
    # utc_end が 2/1 なので 2月の空パーティションも必要
    _empty_spotify = (local_root / "compacted" / "events" / "spotify" / "plays" / "year=2024" / "month=02")
    _empty_spotify.mkdir(parents=True)
    pd.DataFrame({
        "play_id": [], "played_at_utc": [], "track_id": [],
        "track_name": [], "artist_names": [], "ms_played": [],
    }).to_parquet(_empty_spotify / "data.parquet")

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

    utc_start, utc_end = _utc_range(date(2024, 1, 1), date(2024, 1, 31))
    params = QueryParams(
        conn=duckdb_conn,
        r2_config=_build_config(local_root),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        utc_start=utc_start,
        utc_end=utc_end,
        tz_name="UTC",
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
    # utc_end が 2/1 なので 2月の空パーティションも必要
    for _ds, _cols in [
        ("pull_requests", ["pr_event_id", "pr_key", "owner", "repo", "repo_full_name",
         "pr_number", "action", "state", "is_merged", "title", "labels",
         "created_at_utc", "updated_at_utc", "closed_at_utc", "merged_at_utc",
         "additions", "deletions", "changed_files_count", "reviews_count", "commits_count"]),
        ("commits", ["commit_event_id", "owner", "repo", "repo_full_name",
         "sha", "message", "committed_at_utc", "changed_files_count",
         "additions", "deletions"]),
    ]:
        _dir = (local_root / "compacted" / "events" / "github" / _ds / "year=2024" / "month=02")
        _dir.mkdir(parents=True)
        pd.DataFrame({c: [] for c in _cols}).to_parquet(_dir / "data.parquet")

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

    utc_start, utc_end = _utc_range(date(2024, 1, 1), date(2024, 1, 31))
    params = QueryParams(
        conn=duckdb_conn,
        r2_config=_build_config(local_root),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        utc_start=utc_start,
        utc_end=utc_end,
        tz_name="UTC",
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
    # utc_end が 3/22 なので 4月の空パーティションも必要
    _empty_bh = (local_root / "compacted" / "events" / "browser_history" / "page_views" / "year=2026" / "month=04")
    _empty_bh.mkdir(parents=True)
    pd.DataFrame({
        "page_view_id": [], "started_at_utc": [], "ended_at_utc": [],
        "url": [], "title": [], "browser": [], "profile": [],
        "transition": [], "visit_span_count": [],
    }).to_parquet(_empty_bh / "data.parquet")

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

    utc_start, utc_end = _utc_range(date(2026, 3, 20), date(2026, 3, 21))
    params = QueryParams(
        conn=duckdb_conn,
        r2_config=_build_config(local_root),
        start_date=date(2026, 3, 20),
        end_date=date(2026, 3, 21),
        utc_start=utc_start,
        utc_end=utc_end,
        tz_name="UTC",
    )

    page_views = get_page_views(params, browser="edge", profile="Default", limit=10)
    top_domains = get_top_domains(params, limit=10)

    assert [row["page_view_id"] for row in page_views] == ["pv_2", "pv_1"]
    assert top_domains[0]["domain"] == "github.com"
    assert top_domains[0]["page_view_count"] == 2


def test_spotify_queries_with_jst_timezone(duckdb_conn, tmp_path):
    """Asia/Tokyo で日付境界をまたぐデータが正しく取得できること。

    JST 2024-01-01 のデータは UTC では 12/31 15:00 〜 01/01 15:00 にまたがる。
    パーティションは UTC ベースで year=2023/month=12 と year=2024/month=01 に
    分割されている前提。両方読み取れて初めて正しい。
    """
    local_root = tmp_path / "mirror"
    dec_dir = (
        local_root
        / "compacted"
        / "events"
        / "spotify"
        / "plays"
        / "year=2023"
        / "month=12"
    )
    jan_dir = (
        local_root
        / "compacted"
        / "events"
        / "spotify"
        / "plays"
        / "year=2024"
        / "month=01"
    )
    dec_dir.mkdir(parents=True)
    jan_dir.mkdir(parents=True)

    # play_1: JST 2024-01-01 01:00 = UTC 2023-12-31 16:00 → year=2023/month=12
    # play_2: JST 2024-01-01 23:30 = UTC 2024-01-01 14:30 → year=2024/month=01
    # play_3: JST 2024-01-02 00:30 = UTC 2024-01-01 15:30 → year=2024/month=01 (範囲外)
    pd.DataFrame(
        {
            "play_id": ["play_1"],
            "played_at_utc": pd.to_datetime(["2023-12-31 16:00:00"]),
            "track_id": ["track_1"],
            "track_name": ["Song A (prev month)"],
            "artist_names": [["Artist X"]],
            "ms_played": [180000],
        }
    ).to_parquet(dec_dir / "data.parquet")

    pd.DataFrame(
        {
            "play_id": ["play_2", "play_3"],
            "played_at_utc": pd.to_datetime(
                ["2024-01-01 14:30:00", "2024-01-01 15:30:00"]
            ),
            "track_id": ["track_2", "track_3"],
            "track_name": ["Song B", "Song C (excluded)"],
            "artist_names": [["Artist Y"], ["Artist Z"]],
            "ms_played": [180000, 180000],
        }
    ).to_parquet(jan_dir / "data.parquet")

    jst = ZoneInfo("Asia/Tokyo")
    utc_start, utc_end = to_utc_range(date(2024, 1, 1), date(2024, 1, 1), jst)
    # utc_start = 2023-12-31 15:00, utc_end = 2024-01-01 15:00

    params = QueryParams(
        conn=duckdb_conn,
        r2_config=_build_config(local_root),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        utc_start=utc_start,
        utc_end=utc_end,
        tz_name="Asia/Tokyo",
    )

    top_tracks = get_top_tracks(params, limit=5)
    listening_stats = get_listening_stats(params, granularity="day")

    # JST 1/1 に含まれるのは play_1 (前月パーティション) と play_2 (当月)
    # play_3 は utc_end で除外される
    assert len(top_tracks) == 2, (
        f"Expected 2 tracks (cross-partition), got {len(top_tracks)}"
    )
    track_names = {t["track_name"] for t in top_tracks}
    assert "Song A (prev month)" in track_names, (
        "前月パーティションのデータが欠損しています"
    )
    assert "Song B" in track_names
    assert "Song C (excluded)" not in track_names
    # バケットは JST 日付で "2024-01-01"
    assert len(listening_stats) == 1
    assert listening_stats[0]["period"] == "2024-01-01"
