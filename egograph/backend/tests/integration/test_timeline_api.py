"""Daily Timeline の統合テスト。

ローカル compacted Parquet を使って Repository → REST API → MCP Tool の
一連の流れと、Dataset Catalog との契約を検証する。
"""

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
from dataset_catalog import DATASETS_BY_ID, datasets
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
)
from pydantic import SecretStr

from backend.config import R2Config
from backend.dependencies import get_daily_timeline_tool
from backend.domain.tools.timeline.daily import GetDailyTimelineTool
from backend.infrastructure.repositories.timeline_repository import (
    TimelineRepository,
)
from backend.mcp_server import create_mcp_server

JST = ZoneInfo("Asia/Tokyo")

# テスト対象日: 2026-06-28 (JST) = UTC [2026-06-27T15:00, 2026-06-28T15:00)
TARGET_DATE = date(2026, 6, 28)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _local_root(tmp_path: Path) -> Path:
    return tmp_path / "mirror"


def _compacted_dir(local_root: Path, domain: str, dataset_path: str) -> Path:
    return local_root / "compacted" / domain / dataset_path / "year=2026" / "month=06"


def _write_all_sources(tmp_path: Path) -> Path:
    """全 source の compacted Parquet を 2026-06 月に書き出す。"""
    local_root = _local_root(tmp_path)

    # spotify.plays
    spotify_dir = _compacted_dir(local_root, "events", "spotify/plays")
    spotify_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "play_id": "play_1",
                "played_at_utc": _utc("2026-06-28T00:12:03"),
                "track_id": "t1",
                "track_name": "だから僕は僕を辞めた",
                "artist_names": ["ヨルシカ"],
                "album_name": "盗作",
                "ms_played": 222000,
            }
        ]
    ).to_parquet(spotify_dir / "data.parquet")

    # browser_history.page_views（YouTube 視聴ページ）
    browser_dir = _compacted_dir(local_root, "events", "browser_history/page_views")
    browser_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "page_view_id": "pv_1",
                "started_at_utc": _utc("2026-06-28T03:00:00"),
                "ended_at_utc": _utc("2026-06-28T03:00:30"),
                "url": "https://www.youtube.com/watch?v=abc",
                "title": "YouTube Video",
                "browser": "edge",
                "profile": "Default",
                "transition": "link",
                "visit_span_count": 1,
            }
        ]
    ).to_parquet(browser_dir / "data.parquet")

    # youtube.watch_events（同一 video id → correlation 対象）
    youtube_dir = _compacted_dir(local_root, "events", "youtube/watch_events")
    youtube_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "watch_event_id": "we_1",
                "watched_at_utc": _utc("2026-06-28T03:00:30"),
                "video_id": "abc",
                "video_url": "https://www.youtube.com/watch?v=abc",
                "video_title": "YouTube Video",
                "channel_id": "c1",
                "channel_name": "Channel",
                "content_type": "video",
                "source": "browser_history",
                "source_device": "home-pc",
            }
        ]
    ).to_parquet(youtube_dir / "data.parquet")

    # github.commits
    commit_dir = _compacted_dir(local_root, "events", "github/commits")
    commit_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "commit_event_id": "commit_1",
                "owner": "endo-ly",
                "repo": "egograph",
                "repo_full_name": "endo-ly/egograph",
                "sha": "abc123",
                "message": "Add timeline feature\n\nDetail",
                "committed_at_utc": "2026-06-28T05:00:00",
                "changed_files_count": 3,
                "additions": 100,
                "deletions": 10,
            }
        ]
    ).to_parquet(commit_dir / "data.parquet")

    # github.pull_requests
    pr_dir = _compacted_dir(local_root, "events", "github/pull_requests")
    pr_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "pr_event_id": "pr_1",
                "owner": "endo-ly",
                "repo": "egograph",
                "repo_full_name": "endo-ly/egograph",
                "pr_number": 79,
                "action": "opened",
                "state": "open",
                "is_merged": False,
                "title": "Daily Timeline",
                "labels": ["feature"],
                "updated_at_utc": "2026-06-28T06:00:00",
                "additions": 500,
                "deletions": 50,
                "changed_files_count": 8,
            }
        ]
    ).to_parquet(pr_dir / "data.parquet")

    # google_health.daily_metrics
    gh_dir = _compacted_dir(local_root, "events", "google_health/daily_metrics")
    gh_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "data_type": "steps",
                "date": TARGET_DATE,
                "metric_name": "steps",
                "value": 8120.0,
                "unit": "count",
            },
            {
                "data_type": "active-energy-burned",
                "date": TARGET_DATE,
                "metric_name": "active_energy_burned",
                "value": 420.0,
                "unit": "kcal",
            },
            {
                "data_type": "daily-resting-heart-rate",
                "date": TARGET_DATE,
                "metric_name": "resting_heart_rate",
                "value": 53.0,
                "unit": "bpm",
            },
            {
                "data_type": "sleep",
                "date": TARGET_DATE,
                "metric_name": "sleep_duration",
                "value": 21120.0,
                "unit": "second",
            },
        ]
    ).to_parquet(gh_dir / "data.parquet")

    # google_health.sessions（睡眠: 前夜に開始し 6/28 朝に起床）
    sessions_dir = _compacted_dir(local_root, "events", "google_health/sessions")
    sessions_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "data_type": "sleep",
                "started_at_utc": _utc("2026-06-27T14:48:00"),
                "ended_at_utc": _utc("2026-06-27T22:03:00"),
                "duration_seconds": 26100,
                "session_type": "sleep",
            }
        ]
    ).to_parquet(sessions_dir / "data.parquet")

    return local_root


def _build_r2_config(local_root: Path) -> R2Config:
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


def _build_tool(local_root: Path) -> GetDailyTimelineTool:
    repository = TimelineRepository(_build_r2_config(local_root))
    return GetDailyTimelineTool(repository, default_timezone=JST)


# ============================================================
# Repository 統合: 全 source 統合ビュー
# ============================================================


class TestBuildDailyTimelineIntegration:
    """Repository が全 source を統合したビューを正しく構築するか。"""

    def test_builds_full_timeline(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo")

        assert response["date"] == "2026-06-28"
        assert response["timezone"] == "Asia/Tokyo"
        assert response["range"]["start_utc"] == "2026-06-27T15:00:00Z"
        assert response["range"]["end_utc"] == "2026-06-28T15:00:00Z"

        # google_health は items に入らない。残り5件（commit + pr を含む）。
        sources_in_items = {item["source"] for item in response["items"]}
        assert "google_health" not in sources_in_items
        assert sources_in_items == {"spotify", "browser_history", "youtube", "github"}
        assert len(response["items"]) == 5

        # ソート順: spotify → browser_history → youtube → commit → pr
        ordered_sources = [item["source"] for item in response["items"]]
        assert ordered_sources == [
            "spotify",
            "browser_history",
            "youtube",
            "github",
            "github",
        ]

    def test_correlations_link_browser_and_youtube(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        with patch(
            "backend.infrastructure.database.timeline_queries.dataset_has_parquet",
            side_effect=lambda _params, dataset: (
                dataset is not datasets.GOOGLE_HEALTH_DAILY_METRICS
            ),
        ):
            response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo")

        assert len(response["correlations"]) == 1
        correlation = response["correlations"][0]
        assert correlation["reason"] == "same_youtube_video_url_within_120_seconds"
        assert set(correlation["event_ids"]) == {
            "browser_history:page_view:pv_1",
            "youtube:watch_event:we_1",
        }

    def test_gaps_respect_threshold(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(
            date="2026-06-28", timezone="Asia/Tokyo", gap_minutes=120
        )
        # spotify(00:12) → browser(03:00) のみ 120 分超
        assert len(response["gaps"]) == 1
        gap = response["gaps"][0]
        assert gap["duration_minutes"] >= 120
        assert gap["preceded_by_event_id"] == "spotify:play:play_1"
        assert gap["followed_by_event_id"] == "browser_history:page_view:pv_1"

    def test_google_health_daily_summary_attached(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo")

        summary = response["daily_summaries"]["google_health"]
        assert summary["date"] == "2026-06-28"
        assert summary["steps"] == 8120
        assert summary["active_energy_kcal"] == 420
        assert summary["resting_heart_rate_bpm"] == 53
        assert summary["sleep"]["asleep_minutes"] == 352
        assert summary["sleep"]["in_bed_minutes"] == 435
        assert summary["sleep"]["started_at_local"] == "2026-06-27T23:48:00+09:00"
        assert summary["sleep"]["ended_at_local"] == "2026-06-28T07:03:00+09:00"

    def test_coverage_reports_all_sources(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo")

        coverage = response["coverage"]
        assert coverage["spotify"] == {
            "included": True,
            "event_count": 1,
            "status": "ok",
        }
        assert coverage["github"] == {
            "included": True,
            "event_count": 2,
            "status": "ok",
        }
        assert coverage["google_health"]["included"] is True
        assert coverage["google_health"]["status"] == "ok"
        assert coverage["google_health"]["summary_available"] is True

    def test_not_available_when_dataset_missing(self, tmp_path):
        # 全 source を書いたあと youtube の parquet だけ削除
        local_root = _write_all_sources(tmp_path)
        youtube_parquet = (
            local_root
            / "compacted"
            / "events"
            / "youtube"
            / "watch_events"
            / "year=2026"
            / "month=06"
            / "data.parquet"
        )
        youtube_parquet.unlink()

        tool = _build_tool(local_root)
        with patch(
            "backend.infrastructure.database.timeline_queries.dataset_has_parquet",
            side_effect=lambda _params, dataset: (
                dataset is not datasets.YOUTUBE_WATCH_EVENTS
            ),
        ):
            response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo")
        assert response["coverage"]["youtube"]["status"] == "not_available"
        # 他 source は正常取得できる
        assert response["coverage"]["spotify"]["status"] == "ok"

    def test_google_health_not_available_when_dataset_missing(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        # daily_metrics を削除
        gh_parquet = (
            local_root
            / "compacted"
            / "events"
            / "google_health"
            / "daily_metrics"
            / "year=2026"
            / "month=06"
            / "data.parquet"
        )
        gh_parquet.unlink()

        tool = _build_tool(local_root)
        with patch(
            "backend.infrastructure.database.timeline_queries.dataset_has_parquet",
            side_effect=lambda _params, dataset: (
                dataset is not datasets.GOOGLE_HEALTH_DAILY_METRICS
            ),
        ):
            response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo")
        assert response["coverage"]["google_health"]["status"] == "not_available"
        assert "google_health" not in response["daily_summaries"]

    def test_excluded_sources_marked(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(
            date="2026-06-28",
            timezone="Asia/Tokyo",
            sources=["spotify"],
        )
        coverage = response["coverage"]
        assert coverage["spotify"]["status"] == "ok"
        assert coverage["youtube"]["status"] == "excluded"
        assert coverage["google_health"]["status"] == "excluded"
        # spotify のみ items に現れる
        assert {item["source"] for item in response["items"]} == {"spotify"}
        # 除外時は daily_summaries に google_health はない
        assert response["daily_summaries"] == {}

    def test_truncation_respects_limit(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo", limit=2)
        assert response["meta"]["truncated"] is True
        assert len(response["items"]) == 2
        assert response["meta"]["item_count"] == 2

    def test_raw_ref_hidden_by_default(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(date="2026-06-28", timezone="Asia/Tokyo")
        for item in response["items"]:
            assert "raw_ref" not in item

    def test_raw_ref_present_when_requested(self, tmp_path):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        response = tool.execute(
            date="2026-06-28", timezone="Asia/Tokyo", include_raw_refs=True
        )
        for item in response["items"]:
            assert item["raw_ref"]["dataset_id"] in DATASETS_BY_ID


# ============================================================
# REST API と MCP Tool の契約一致
# ============================================================


class TestRestAndMcpContract:
    """REST API と MCP Tool が同じ response shape を返す。"""

    def test_rest_and_tool_return_same_shape(self, tmp_path, test_client):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        test_client.app.dependency_overrides[get_daily_timeline_tool] = lambda: tool

        params = {
            "date": "2026-06-28",
            "timezone": "Asia/Tokyo",
            "gap_minutes": 120,
            "include_correlations": "true",
            "include_raw_refs": "true",
            "limit": 500,
        }
        response = test_client.get(
            "/v1/data/timeline/daily",
            params=params,
            headers={"X-API-Key": "test-backend-key"},
        )
        assert response.status_code == 200
        rest_body = response.json()

        tool_body = tool.execute(
            date="2026-06-28",
            timezone="Asia/Tokyo",
            gap_minutes=120,
            include_correlations=True,
            include_raw_refs=True,
            limit=500,
        )
        # generated_at は呼び出しごとに変わるため除外して比較
        rest_body["meta"].pop("generated_at", None)
        tool_body["meta"].pop("generated_at", None)
        assert rest_body == tool_body

    def test_rest_returns_400_on_invalid_date(self, tmp_path, test_client):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        test_client.app.dependency_overrides[get_daily_timeline_tool] = lambda: tool

        response = test_client.get(
            "/v1/data/timeline/daily?date=not-a-date",
            headers={"X-API-Key": "test-backend-key"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "invalid_date: expected YYYY-MM-DD"

    def test_rest_returns_400_on_invalid_gap(self, tmp_path, test_client):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        test_client.app.dependency_overrides[get_daily_timeline_tool] = lambda: tool

        response = test_client.get(
            "/v1/data/timeline/daily?date=2026-06-28&gap_minutes=9999",
            headers={"X-API-Key": "test-backend-key"},
        )
        assert response.status_code == 400
        assert "invalid_gap_minutes" in response.json()["detail"]

    def test_rest_returns_400_on_invalid_gap_type(self, tmp_path, test_client):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        test_client.app.dependency_overrides[get_daily_timeline_tool] = lambda: tool

        response = test_client.get(
            "/v1/data/timeline/daily?date=2026-06-28&gap_minutes=abc",
            headers={"X-API-Key": "test-backend-key"},
        )
        assert response.status_code == 400
        assert "invalid_gap_minutes" in response.json()["detail"]

    def test_rest_returns_400_on_invalid_limit_type(self, tmp_path, test_client):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        test_client.app.dependency_overrides[get_daily_timeline_tool] = lambda: tool

        response = test_client.get(
            "/v1/data/timeline/daily?date=2026-06-28&limit=abc",
            headers={"X-API-Key": "test-backend-key"},
        )
        assert response.status_code == 400
        assert "invalid_limit" in response.json()["detail"]

    def test_rest_returns_400_on_invalid_boolean_type(self, tmp_path, test_client):
        local_root = _write_all_sources(tmp_path)
        tool = _build_tool(local_root)
        test_client.app.dependency_overrides[get_daily_timeline_tool] = lambda: tool

        response = test_client.get(
            "/v1/data/timeline/daily"
            "?date=2026-06-28&include_correlations=maybe",
            headers={"X-API-Key": "test-backend-key"},
        )
        assert response.status_code == 400
        assert "invalid_include_correlations" in response.json()["detail"]

    def test_rest_requires_api_key(self, test_client):
        response = test_client.get("/v1/data/timeline/daily?date=2026-06-28")
        assert response.status_code == 401


class TestMcpServerRegistration:
    """MCP ToolRegistry に get_daily_timeline が登録される。"""

    def test_registry_includes_timeline_tool(self, mock_backend_config):
        server = create_mcp_server(mock_backend_config)
        handler = server._mcp_server.request_handlers[ListToolsRequest]
        result = asyncio.run(handler(ListToolsRequest(method="tools/list"))).root
        tool_names = [tool.name for tool in result.tools]
        assert "get_daily_timeline" in tool_names

    def test_mcp_call_returns_json_payload(self, tmp_path, mock_backend_config):
        local_root = _write_all_sources(tmp_path)
        # mock_backend_config が指す local root をテストデータへ差し替え
        mock_backend_config.r2.local_parquet_root = str(local_root)

        server = create_mcp_server(mock_backend_config)
        handler = server._mcp_server.request_handlers[CallToolRequest]
        request = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="get_daily_timeline",
                arguments={
                    "date": "2026-06-28",
                    "timezone": "Asia/Tokyo",
                    "include_raw_refs": True,
                },
            ),
        )
        result = asyncio.run(handler(request)).root
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload["date"] == "2026-06-28"
        assert len(payload["items"]) == 5
        assert "google_health" in payload["daily_summaries"]
