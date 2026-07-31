"""Daily Timeline リポジトリの純粋論理の単体テスト。

正規化、ソート、correlation、gap、local 時刻付与、Google Health 日次サマリ構築など、
DuckDB に依存しない関数を検証する。
"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from dataset_catalog import datasets
from pydantic import SecretStr

from backend.config import R2Config
from backend.infrastructure.database.query_params import QueryParams
from backend.infrastructure.database.timeline_queries import dataset_has_parquet
from backend.infrastructure.repositories.timeline_repository import (
    _build_range,
    _compose_google_health_summary,
    apply_raw_refs,
    build_correlations,
    build_gaps,
    finalize_item_times,
    normalize_browser_page_view,
    normalize_github_commit,
    normalize_github_pull_request,
    normalize_spotify_play,
    normalize_youtube_watch,
    sort_items,
)

JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc


def _dt(iso: str) -> datetime:
    """ISO 文字列を UTC aware datetime にする。"""
    return datetime.fromisoformat(iso).astimezone(UTC)


# ============================================================
# 正規化
# ============================================================


class TestNormalizeSpotifyPlay:
    def test_builds_common_shape_with_duration(self):
        row = {
            "play_id": "abc123",
            "played_at_utc": datetime(2026, 6, 28, 0, 12, 3),
            "track_id": "t1",
            "track_name": "だから僕は僕を辞めた",
            "artist_names": ["ヨルシカ"],
            "album_name": "盗作",
            "ms_played": 222000,
        }
        item = normalize_spotify_play(row)

        assert item["event_id"] == "spotify:play:abc123"
        assert item["source"] == "spotify"
        assert item["kind"] == "music_play"
        assert item["started_at_utc"] == _dt("2026-06-28T00:12:03+00:00")
        assert item["title"] == "ヨルシカ - だから僕は僕を辞めた"
        assert item["subtitle"] == "Spotify play"
        assert item["duration_seconds"] == 222
        assert item["raw_ref"] == {
            "dataset_id": "spotify.plays",
            "record_id": "abc123",
            "timestamp_column": "played_at_utc",
        }
        assert item["metadata"]["track_name"] == "だから僕は僕を辞めた"

    def test_duration_omitted_when_ms_played_zero(self):
        row = {
            "play_id": "p1",
            "played_at_utc": datetime(2026, 6, 28, 0, 12, 3),
            "track_id": "t1",
            "track_name": "Song",
            "artist_names": [],
            "album_name": None,
            "ms_played": 0,
        }
        item = normalize_spotify_play(row)
        assert item["duration_seconds"] is None
        # artist がないときは track_name だけ
        assert item["title"] == "Song"


class TestNormalizeBrowserPageView:
    def test_builds_item_with_domain_subtitle_and_duration(self):
        row = {
            "page_view_id": "pv_1",
            "started_at_utc": datetime(2026, 6, 28, 1, 30, 0),
            "ended_at_utc": datetime(2026, 6, 28, 1, 30, 45),
            "url": "https://docs.example.com/page",
            "title": "Example Page",
            "browser": "edge",
            "profile": "Default",
            "transition": "link",
            "visit_span_count": 2,
        }
        item = normalize_browser_page_view(row)

        assert item["event_id"] == "browser_history:page_view:pv_1"
        assert item["kind"] == "page_view"
        assert item["subtitle"] == "docs.example.com"
        assert item["url"] == "https://docs.example.com/page"
        assert item["duration_seconds"] == 45
        assert item["raw_ref"]["dataset_id"] == "browser_history.page_views"

    def test_no_ended_at_yields_no_duration(self):
        row = {
            "page_view_id": "pv_2",
            "started_at_utc": datetime(2026, 6, 28, 2, 0, 0),
            "ended_at_utc": None,
            "url": "https://x.com",
            "title": "X",
            "browser": "edge",
            "profile": "Default",
            "transition": "link",
            "visit_span_count": 1,
        }
        item = normalize_browser_page_view(row)
        assert item["duration_seconds"] is None
        assert item["ended_at_utc"] is None


class TestNormalizeYoutubeWatch:
    def test_builds_item(self):
        row = {
            "watch_event_id": "we_1",
            "watched_at_utc": datetime(2026, 6, 28, 3, 0, 0),
            "video_id": "v1",
            "video_url": "https://www.youtube.com/watch?v=v1",
            "video_title": "Title",
            "channel_id": "c1",
            "channel_name": "Channel",
            "content_type": "video",
            "source": "browser_history",
            "source_device": "home-pc",
        }
        item = normalize_youtube_watch(row)

        assert item["event_id"] == "youtube:watch_event:we_1"
        assert item["kind"] == "youtube_watch"
        assert item["duration_seconds"] is None
        assert item["url"] == "https://www.youtube.com/watch?v=v1"
        assert item["subtitle"] == "Channel"


class TestNormalizeGithub:
    def test_commit_uses_first_message_line(self):
        row = {
            "commit_event_id": "c1",
            "owner": "o",
            "repo": "r",
            "repo_full_name": "o/r",
            "sha": "abc",
            "message": "Add timeline feature\n\nDetailed body",
            "committed_at_utc": datetime(2026, 6, 28, 4, 0, 0),
            "changed_files_count": 3,
            "additions": 10,
            "deletions": 2,
        }
        item = normalize_github_commit(row)
        assert item["event_id"] == "github:commit:c1"
        assert item["kind"] == "github_commit"
        assert item["title"] == "Add timeline feature"
        assert item["subtitle"] == "o/r"
        assert item["duration_seconds"] is None

    def test_pull_request_uses_updated_at(self):
        row = {
            "pr_event_id": "pr1",
            "owner": "o",
            "repo": "r",
            "repo_full_name": "o/r",
            "pr_number": 12,
            "action": "opened",
            "state": "open",
            "is_merged": False,
            "title": "Fix bug",
            "labels": ["bug"],
            "updated_at_utc": datetime(2026, 6, 28, 5, 0, 0),
            "additions": 1,
            "deletions": 1,
            "changed_files_count": 1,
        }
        item = normalize_github_pull_request(row)
        assert item["event_id"] == "github:pull_request:pr1"
        assert item["kind"] == "github_pull_request"
        assert item["started_at_utc"] == _dt("2026-06-28T05:00:00+00:00")
        assert item["title"] == "Fix bug"


# ============================================================
# ソート
# ============================================================


class TestSortItems:
    def test_sorts_by_started_at_utc(self):
        items = [
            {
                "event_id": "b",
                "source": "spotify",
                "started_at_utc": _dt("2026-06-28T02:00:00+00:00"),
            },
            {
                "event_id": "a",
                "source": "spotify",
                "started_at_utc": _dt("2026-06-28T01:00:00+00:00"),
            },
        ]
        ordered = sort_items(items)
        assert [i["event_id"] for i in ordered] == ["a", "b"]

    def test_same_time_uses_source_priority(self):
        same_time = _dt("2026-06-28T01:00:00+00:00")
        items = [
            {"event_id": "z", "source": "spotify", "started_at_utc": same_time},
            {"event_id": "y", "source": "youtube", "started_at_utc": same_time},
            {"event_id": "x", "source": "browser_history", "started_at_utc": same_time},
            {"event_id": "w", "source": "github", "started_at_utc": same_time},
        ]
        ordered = sort_items(items)
        assert [i["source"] for i in ordered] == [
            "browser_history",
            "youtube",
            "spotify",
            "github",
        ]

    def test_same_time_same_source_uses_event_id(self):
        same_time = _dt("2026-06-28T01:00:00+00:00")
        items = [
            {
                "event_id": "spotify:play:b",
                "source": "spotify",
                "started_at_utc": same_time,
            },
            {
                "event_id": "spotify:play:a",
                "source": "spotify",
                "started_at_utc": same_time,
            },
        ]
        ordered = sort_items(items)
        assert [i["event_id"] for i in ordered] == ["spotify:play:a", "spotify:play:b"]


# ============================================================
# Correlation
# ============================================================


class TestBuildCorrelations:
    def test_same_video_url_within_window(self):
        t = _dt("2026-06-28T01:00:00+00:00")
        items = [
            {
                "event_id": "browser_history:page_view:pv_1",
                "source": "browser_history",
                "started_at_utc": t,
                "url": "https://www.youtube.com/watch?v=abc",
            },
            {
                "event_id": "youtube:watch_event:we_1",
                "source": "youtube",
                "started_at_utc": t,
                "url": "https://youtube.com/watch?v=abc",
            },
        ]
        correlations = build_correlations(items)
        assert len(correlations) == 1
        correlation = correlations[0]
        assert correlation["reason"] == "same_youtube_video_url_within_120_seconds"
        assert correlation["confidence"] == 0.95
        assert correlation["correlation_id"].startswith("corr_")

    def test_youtube_url_without_video_id_near_watch_event(self):
        t = _dt("2026-06-28T01:00:00+00:00")
        items = [
            {
                "event_id": "browser_history:page_view:pv_1",
                "source": "browser_history",
                "started_at_utc": t,
                "url": "https://www.youtube.com/feed/subscriptions",
            },
            {
                "event_id": "youtube:watch_event:we_1",
                "source": "youtube",
                "started_at_utc": t,
                "url": "https://youtube.com/watch?v=xyz",
            },
        ]
        correlations = build_correlations(items)
        assert len(correlations) == 1
        assert correlations[0]["reason"] == "youtube_url_near_watch_event"
        assert correlations[0]["confidence"] == 0.75

    def test_no_correlation_outside_window(self):
        items = [
            {
                "event_id": "browser_history:page_view:pv_1",
                "source": "browser_history",
                "started_at_utc": _dt("2026-06-28T01:00:00+00:00"),
                "url": "https://www.youtube.com/watch?v=abc",
            },
            {
                "event_id": "youtube:watch_event:we_1",
                "source": "youtube",
                "started_at_utc": _dt("2026-06-28T01:05:00+00:00"),
                "url": "https://youtube.com/watch?v=abc",
            },
        ]
        assert build_correlations(items) == []

    def test_does_not_remove_or_merge_items(self):
        t = _dt("2026-06-28T01:00:00+00:00")
        items = [
            {
                "event_id": "browser_history:page_view:pv_1",
                "source": "browser_history",
                "started_at_utc": t,
                "url": "https://www.youtube.com/watch?v=abc",
            },
            {
                "event_id": "youtube:watch_event:we_1",
                "source": "youtube",
                "started_at_utc": t,
                "url": "https://youtube.com/watch?v=abc",
            },
        ]
        build_correlations(items)
        assert len(items) == 2  # correlation は注釈のみ


# ============================================================
# Gap
# ============================================================


class TestBuildGaps:
    def _item(self, event_id: str, iso: str):
        return {
            "event_id": event_id,
            "source": "spotify",
            "started_at_utc": _dt(iso),
        }

    def test_emits_gap_when_above_threshold(self):
        items = [
            self._item("a", "2026-06-28T01:00:00+00:00"),
            self._item("b", "2026-06-28T01:30:00+00:00"),
            self._item("c", "2026-06-28T04:00:00+00:00"),
        ]
        gaps = build_gaps(items, gap_minutes=120, timezone=JST)
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap["kind"] == "no_observed_events_gap"
        assert gap["duration_minutes"] == 150
        assert gap["preceded_by_event_id"] == "b"
        assert gap["followed_by_event_id"] == "c"
        assert gap["gap_id"] == "gap_20260628_1030_1300"

    def test_no_gap_when_disabled(self):
        items = [
            self._item("a", "2026-06-28T01:00:00+00:00"),
            self._item("b", "2026-06-28T10:00:00+00:00"),
        ]
        assert build_gaps(items, gap_minutes=None, timezone=JST) == []
        assert build_gaps(items, gap_minutes=0, timezone=JST) == []

    def test_no_gap_with_single_item(self):
        items = [self._item("a", "2026-06-28T01:00:00+00:00")]
        assert build_gaps(items, gap_minutes=120, timezone=JST) == []


# ============================================================
# local 時刻付与 / raw_ref 制御
# ============================================================


class TestFinalizeItemTimesAndRawRefs:
    def test_finalizes_utc_and_local_times(self):
        items = [
            {
                "started_at_utc": _dt("2026-06-27T15:00:00+00:00"),
                "started_at_local": None,
                "ended_at_utc": None,
                "ended_at_local": None,
            }
        ]
        finalize_item_times(items, JST)
        assert items[0]["started_at_utc"] == "2026-06-27T15:00:00Z"
        assert items[0]["started_at_local"] == "2026-06-28T00:00:00+09:00"
        assert items[0]["ended_at_utc"] is None
        assert items[0]["ended_at_local"] is None

    def test_apply_raw_refs_false_removes_raw_ref(self):
        items = [{"event_id": "x", "raw_ref": {"dataset_id": "d", "record_id": "r"}}]
        apply_raw_refs(items, include=False)
        assert "raw_ref" not in items[0]

    def test_apply_raw_refs_true_keeps_raw_ref(self):
        items = [{"event_id": "x", "raw_ref": {"dataset_id": "d", "record_id": "r"}}]
        apply_raw_refs(items, include=True)
        assert items[0]["raw_ref"]["dataset_id"] == "d"


# ============================================================
# Range / Google Health 日次サマリ
# ============================================================


class TestBuildRange:
    def test_builds_local_and_utc_range(self):
        utc_start = datetime(2026, 6, 27, 15, 0, 0)
        utc_end = datetime(2026, 6, 28, 15, 0, 0)
        result = _build_range(date(2026, 6, 28), JST, utc_start, utc_end)
        assert result["start_local"] == "2026-06-28T00:00:00+09:00"
        assert result["end_local"] == "2026-06-29T00:00:00+09:00"
        assert result["start_utc"] == "2026-06-27T15:00:00Z"
        assert result["end_utc"] == "2026-06-28T15:00:00Z"


class TestDatasetHasParquet:
    def test_uses_r2_glob_even_when_local_dataset_exists(self, tmp_path):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (1,)
        local_dataset = (
            tmp_path
            / "compacted"
            / "events"
            / "spotify"
            / "plays"
            / "year=2026"
            / "month=06"
        )
        local_dataset.mkdir(parents=True)
        (local_dataset / "data.parquet").write_bytes(b"local-only")
        config = R2Config.model_construct(
            endpoint_url="https://test.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key=SecretStr("test_secret"),
            bucket_name="test-bucket",
            raw_path="raw/",
            events_path="events/",
            master_path="master/",
            local_parquet_root=str(tmp_path),
        )
        params = QueryParams(
            conn=conn,
            r2_config=config,
            start_date=date(2026, 6, 28),
            end_date=date(2026, 6, 28),
            utc_start=datetime(2026, 6, 27, 15, 0, 0),
            utc_end=datetime(2026, 6, 28, 15, 0, 0),
            tz_name="Asia/Tokyo",
        )

        assert dataset_has_parquet(params, datasets.SPOTIFY_PLAYS) is True
        conn.execute.assert_called_once_with(
            "SELECT COUNT(*) FROM glob(?)",
            ("s3://test-bucket/compacted/events/spotify/plays/**/*.parquet",),
        )


class TestComposeGoogleHealthSummary:
    def test_builds_summary_with_sleep_sessions(self):
        metrics = {
            "steps": 8120.0,
            "active_energy_burned": 420.0,
            "resting_heart_rate": 53.0,
            "sleep_duration_seconds": 21120.0,  # 352 min
        }
        sessions = [
            {
                "started_at_utc": datetime(2026, 6, 27, 14, 48),
                "ended_at_utc": datetime(2026, 6, 27, 22, 3),
                "duration_seconds": 26100,
                "session_type": "sleep",
            }
        ]
        summary = _compose_google_health_summary(
            metrics, sessions, date(2026, 6, 28), JST
        )
        assert summary is not None
        assert summary["date"] == "2026-06-28"
        assert summary["timezone"] == "Asia/Tokyo"
        assert summary["steps"] == 8120
        assert summary["active_energy_kcal"] == 420
        assert summary["resting_heart_rate_bpm"] == 53
        assert summary["sleep"]["asleep_minutes"] == 352
        assert summary["sleep"]["in_bed_minutes"] == 435
        assert summary["sleep"]["started_at_local"] == "2026-06-27T23:48:00+09:00"
        assert summary["sleep"]["ended_at_local"] == "2026-06-28T07:03:00+09:00"

    def test_returns_none_when_no_data(self):
        summary = _compose_google_health_summary({}, [], date(2026, 6, 28), JST)
        assert summary is None

    def test_sleep_duration_only_without_sessions(self):
        metrics = {"sleep_duration_seconds": 36000.0}
        summary = _compose_google_health_summary(metrics, [], date(2026, 6, 28), JST)
        assert summary is not None
        assert summary["sleep"] == {"asleep_minutes": 600}
