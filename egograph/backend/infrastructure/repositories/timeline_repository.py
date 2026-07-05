"""Daily Timeline リポジトリ。

複数 source の観測イベントを1日単位で時刻順に統合する read model を構築する。

責務:
    - source ごとの raw クエリ呼び出し
    - 共通 shape への正規化
    - ``started_at_utc`` + source priority による安定ソート
    - Browser History / YouTube 関連候補（correlation）の生成
    - 観測 gap の生成
    - source ごとの coverage 生成
    - Google Health 日次サマリの添付

純粋論理（正規化・ソート・correlation・gap）はモジュール直下の関数として切り出し、
DuckDB に依存せず単体テスト可能にしている。これは「UTC range を入力にした builder」
として将来の別契約でも再利用できるようにするため。
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from dataset_catalog import datasets

from backend.config import R2Config
from backend.constants import (
    CORRELATION_YOUTUBE_WINDOW_SECONDS,
    TIMELINE_SOURCE_PRIORITY,
    TIMELINE_SOURCES,
)
from backend.infrastructure.database import timeline_queries as queries
from backend.infrastructure.database.connection import DuckDBConnection
from backend.infrastructure.database.query_params import QueryParams
from backend.validators import to_utc_range

logger = logging.getLogger(__name__)

# event_id の中央要素（dataset に安定した短名を与える）。
_EVENT_TYPE_SUFFIX = {
    "spotify:music_play": "play",
    "browser_history:page_view": "page_view",
    "youtube:youtube_watch": "watch_event",
    "github:github_commit": "commit",
    "github:github_pull_request": "pull_request",
}

# source ごとの代表 dataset（存在確認用）と、items 系 source の取得計画。
_ITEM_SOURCE_DATASETS = {
    "spotify": datasets.SPOTIFY_PLAYS,
    "youtube": datasets.YOUTUBE_WATCH_EVENTS,
    "browser_history": datasets.BROWSER_HISTORY_PAGE_VIEWS,
    "github:commits": datasets.GITHUB_COMMITS,
    "github:pull_requests": datasets.GITHUB_PULL_REQUESTS,
}


class TimelineRepository:
    """Daily Timeline の統合ビューを構築するリポジトリ。"""

    def __init__(self, r2_config: R2Config) -> None:
        self.r2_config = r2_config

    def build_daily_timeline(
        self,
        *,
        date_local: date,
        timezone: ZoneInfo,
        sources: set[str],
        gap_minutes: int | None,
        include_correlations: bool,
        include_raw_refs: bool,
        limit: int,
    ) -> dict[str, Any]:
        """1日分のタイムライン応答を構築する。

        Args:
            date_local: ``timezone`` 上のローカル日付。
            timezone: 日付範囲と表示用 local 時刻の生成に使うタイムゾーン。
            sources: 含める source の集合。空なら全 source。
            gap_minutes: この分数以上の観測欠落を gap とする。``None`` または
                ``0`` のときは gap 検出を行わない。
            include_correlations: ``True`` なら関連候補を生成する。
            include_raw_refs: ``True`` なら ``raw_ref`` を各 item に付与する。
            limit: ``items`` の最大件数。
        """
        effective_sources = set(sources) if sources else set(TIMELINE_SOURCES)
        utc_start, utc_end = to_utc_range(date_local, date_local, timezone)

        with DuckDBConnection(self.r2_config) as conn:
            params = QueryParams(
                conn=conn,
                r2_config=self.r2_config,
                start_date=date_local,
                end_date=date_local,
                utc_start=utc_start,
                utc_end=utc_end,
                tz_name=str(timezone),
            )
            items, coverage = self._collect_items(params, effective_sources)
            google_health_summary, gh_dataset_exists = (
                self._build_google_health_summary(
                    params, date_local, timezone, effective_sources
                )
            )

        coverage = self._finalize_coverage(
            coverage,
            effective_sources=effective_sources,
            google_health_dataset_exists=gh_dataset_exists,
            google_health_summary_available=google_health_summary is not None,
        )

        items = sort_items(items)
        truncated = len(items) > limit
        items = items[:limit]
        apply_raw_refs(items, include_raw_refs)

        correlations = build_correlations(items) if include_correlations else []
        gaps = build_gaps(items, gap_minutes=gap_minutes, timezone=timezone)

        # gap / correlation の計算が終わったあとに UTC / local を ISO 文字列へ直列化する
        finalize_item_times(items, timezone)

        daily_summaries: dict[str, Any] = {}
        if google_health_summary is not None:
            daily_summaries["google_health"] = google_health_summary

        logger.info(
            "Built daily timeline: date=%s, tz=%s, items=%s, correlations=%s, "
            "gaps=%s, truncated=%s",
            date_local,
            timezone,
            len(items),
            len(correlations),
            len(gaps),
            truncated,
        )
        return {
            "date": date_local.isoformat(),
            "timezone": str(timezone),
            "range": _build_range(date_local, timezone, utc_start, utc_end),
            "items": items,
            "correlations": correlations,
            "gaps": gaps,
            "daily_summaries": daily_summaries,
            "coverage": coverage,
            "meta": {
                "item_count": len(items),
                "truncated": truncated,
                "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }

    # ------------------------------------------------------------------
    # items 収集
    # ------------------------------------------------------------------

    def _collect_items(
        self,
        params: QueryParams,
        effective_sources: set[str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """各 source の raw クエリを呼び出し、正規化 item と coverage を返す。"""
        items: list[dict[str, Any]] = []
        coverage: dict[str, Any] = {}

        single_source_plan = (
            ("spotify", queries.fetch_spotify_plays, normalize_spotify_play),
            (
                "browser_history",
                queries.fetch_browser_page_views,
                normalize_browser_page_view,
            ),
            ("youtube", queries.fetch_youtube_watch_events, normalize_youtube_watch),
        )
        for source, fetcher, normalizer in single_source_plan:
            coverage[source] = self._collect_single_source(
                params,
                source=source,
                dataset=_ITEM_SOURCE_DATASETS[source],
                fetcher=fetcher,
                normalizer=normalizer,
                included=source in effective_sources,
                items=items,
            )

        coverage["github"] = self._collect_github(params, effective_sources, items)
        return items, coverage

    def _collect_single_source(
        self,
        params: QueryParams,
        *,
        source: str,
        dataset,
        fetcher,
        normalizer,
        included: bool,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not included:
            return _coverage_excluded()
        if not queries.dataset_has_parquet(params, dataset):
            return _coverage_not_available()
        raw_rows = fetcher(params)
        items.extend(normalizer(row) for row in raw_rows)
        return _coverage_ok(len(raw_rows))

    def _collect_github(
        self,
        params: QueryParams,
        effective_sources: set[str],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if "github" not in effective_sources:
            return _coverage_excluded()

        plan = (
            (
                _ITEM_SOURCE_DATASETS["github:commits"],
                queries.fetch_github_commits,
                normalize_github_commit,
            ),
            (
                _ITEM_SOURCE_DATASETS["github:pull_requests"],
                queries.fetch_github_pull_requests,
                normalize_github_pull_request,
            ),
        )
        any_exists = False
        count = 0
        for dataset, fetcher, normalizer in plan:
            if not queries.dataset_has_parquet(params, dataset):
                continue
            any_exists = True
            raw_rows = fetcher(params)
            items.extend(normalizer(row) for row in raw_rows)
            count += len(raw_rows)
        return _coverage_ok(count) if any_exists else _coverage_not_available()

    # ------------------------------------------------------------------
    # Google Health 日次サマリ
    # ------------------------------------------------------------------

    def _build_google_health_summary(
        self,
        params: QueryParams,
        date_local: date,
        tz: ZoneInfo,
        effective_sources: set[str],
    ) -> tuple[dict[str, Any] | None, bool]:
        """Google Health 日次サマリと、daily_metrics dataset の存在可否を返す。"""
        dataset = datasets.GOOGLE_HEALTH_DAILY_METRICS
        if "google_health" not in effective_sources:
            return None, False
        dataset_exists = queries.dataset_has_parquet(params, dataset)
        if not dataset_exists:
            return None, False

        metrics = queries.fetch_google_health_daily_metrics(params)
        sleep_sessions = queries.fetch_google_health_sleep_sessions(params)
        summary = _compose_google_health_summary(
            metrics, sleep_sessions, date_local, tz
        )
        return summary, True

    def _finalize_coverage(
        self,
        coverage: dict[str, Any],
        *,
        effective_sources: set[str],
        google_health_dataset_exists: bool,
        google_health_summary_available: bool,
    ) -> dict[str, Any]:
        """google_health の coverage を決定し、順序を安定させる。"""
        ordered: dict[str, Any] = {}
        for source in TIMELINE_SOURCES:
            if source in coverage:
                ordered[source] = coverage[source]
            elif source == "google_health":
                if "google_health" not in effective_sources:
                    ordered["google_health"] = _coverage_excluded()
                elif not google_health_dataset_exists:
                    ordered["google_health"] = _coverage_not_available()
                else:
                    ordered["google_health"] = {
                        "included": True,
                        "event_count": 0,
                        "status": "ok",
                        "summary_available": google_health_summary_available,
                    }
        return ordered


# ============================================================
# 正規化関数: raw 行 → 共通 shape の timeline item
# ============================================================


def normalize_spotify_play(row: dict[str, Any]) -> dict[str, Any]:
    """Spotify 再生行を timeline item に正規化する。"""
    record_id = str(row["play_id"])
    artists = row.get("artist_names") or []
    primary_artist = artists[0] if len(artists) >= 1 else None
    track_name = row.get("track_name")
    title = (
        f"{primary_artist} - {track_name}"
        if primary_artist and track_name
        else (track_name or primary_artist or "Spotify play")
    )
    ms_played = _as_float(row.get("ms_played"))
    duration_seconds = int(ms_played / 1000) if ms_played and ms_played > 0 else None

    return {
        "event_id": _event_id("spotify", "music_play", record_id),
        "source": "spotify",
        "kind": "music_play",
        "started_at_utc": _to_utc(row.get("played_at_utc")),
        "started_at_local": None,
        "ended_at_utc": None,
        "ended_at_local": None,
        "duration_seconds": duration_seconds,
        "title": title,
        "subtitle": "Spotify play",
        "url": None,
        "raw_ref": _raw_ref("spotify.plays", record_id, "played_at_utc"),
        "metadata": {
            "play_id": record_id,
            "track_id": row.get("track_id"),
            "track_name": track_name,
            "artist_names": list(artists),
            "album_name": row.get("album_name"),
            "ms_played": ms_played,
        },
    }


def normalize_browser_page_view(row: dict[str, Any]) -> dict[str, Any]:
    """Browser History page view 行を timeline item に正規化する。"""
    record_id = str(row["page_view_id"])
    started = _to_utc(row.get("started_at_utc"))
    ended = _to_utc(row.get("ended_at_utc"))
    url = row.get("url")

    return {
        "event_id": _event_id("browser_history", "page_view", record_id),
        "source": "browser_history",
        "kind": "page_view",
        "started_at_utc": started,
        "started_at_local": None,
        "ended_at_utc": ended,
        "ended_at_local": None,
        "duration_seconds": _duration_seconds(started, ended),
        "title": row.get("title") or url or "Untitled page",
        "subtitle": _domain_of(url),
        "url": url,
        "raw_ref": _raw_ref("browser_history.page_views", record_id, "started_at_utc"),
        "metadata": {
            "page_view_id": record_id,
            "browser": row.get("browser"),
            "profile": row.get("profile"),
            "transition": row.get("transition"),
            "visit_span_count": row.get("visit_span_count"),
        },
    }


def normalize_youtube_watch(row: dict[str, Any]) -> dict[str, Any]:
    """YouTube 視聴イベント行を timeline item に正規化する。"""
    record_id = str(row["watch_event_id"])
    return {
        "event_id": _event_id("youtube", "youtube_watch", record_id),
        "source": "youtube",
        "kind": "youtube_watch",
        "started_at_utc": _to_utc(row.get("watched_at_utc")),
        "started_at_local": None,
        "ended_at_utc": None,
        "ended_at_local": None,
        "duration_seconds": None,
        "title": row.get("video_title") or "YouTube watch",
        "subtitle": row.get("channel_name"),
        "url": row.get("video_url"),
        "raw_ref": _raw_ref("youtube.watch_events", record_id, "watched_at_utc"),
        "metadata": {
            "watch_event_id": record_id,
            "video_id": row.get("video_id"),
            "channel_id": row.get("channel_id"),
            "channel_name": row.get("channel_name"),
            "content_type": row.get("content_type"),
            "source": row.get("source"),
            "source_device": row.get("source_device"),
        },
    }


def normalize_github_commit(row: dict[str, Any]) -> dict[str, Any]:
    """GitHub commit 行を timeline item に正規化する。"""
    record_id = str(row["commit_event_id"])
    return {
        "event_id": _event_id("github", "github_commit", record_id),
        "source": "github",
        "kind": "github_commit",
        "started_at_utc": _to_utc(row.get("committed_at_utc")),
        "started_at_local": None,
        "ended_at_utc": None,
        "ended_at_local": None,
        "duration_seconds": None,
        "title": _commit_title(row.get("message")),
        "subtitle": row.get("repo_full_name"),
        "url": None,
        "raw_ref": _raw_ref("github.commits", record_id, "committed_at_utc"),
        "metadata": {
            "commit_event_id": record_id,
            "sha": row.get("sha"),
            "owner": row.get("owner"),
            "repo": row.get("repo"),
            "additions": row.get("additions"),
            "deletions": row.get("deletions"),
            "changed_files_count": row.get("changed_files_count"),
        },
    }


def normalize_github_pull_request(row: dict[str, Any]) -> dict[str, Any]:
    """GitHub Pull Request 行を timeline item に正規化する。"""
    record_id = str(row["pr_event_id"])
    return {
        "event_id": _event_id("github", "github_pull_request", record_id),
        "source": "github",
        "kind": "github_pull_request",
        "started_at_utc": _to_utc(row.get("updated_at_utc")),
        "started_at_local": None,
        "ended_at_utc": None,
        "ended_at_local": None,
        "duration_seconds": None,
        "title": row.get("title") or "Pull Request",
        "subtitle": row.get("repo_full_name"),
        "url": None,
        "raw_ref": _raw_ref("github.pull_requests", record_id, "updated_at_utc"),
        "metadata": {
            "pr_event_id": record_id,
            "pr_number": row.get("pr_number"),
            "action": row.get("action"),
            "state": row.get("state"),
            "is_merged": row.get("is_merged"),
            "owner": row.get("owner"),
            "repo": row.get("repo"),
            "labels": list(row.get("labels") or []),
            "additions": row.get("additions"),
            "deletions": row.get("deletions"),
            "changed_files_count": row.get("changed_files_count"),
        },
    }


# ============================================================
# ソート
# ============================================================


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``started_at_utc`` 昇順、source priority、event_id で安定ソートする。"""
    return sorted(
        items,
        key=lambda item: (
            item["started_at_utc"] or datetime.max.replace(tzinfo=UTC),
            TIMELINE_SOURCE_PRIORITY.get(item["source"], 99),
            item["event_id"],
        ),
    )


# ============================================================
# Correlation
# ============================================================


def build_correlations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Browser History と YouTube の関連候補を生成する。

    ``items`` の削除や統合は行わず、注釈のみを返す。
    """
    page_views = [item for item in items if item["source"] == "browser_history"]
    watches = [item for item in items if item["source"] == "youtube"]
    if not page_views or not watches:
        return []

    correlations: list[dict[str, Any]] = []
    for page_view in page_views:
        pv_started = page_view["started_at_utc"]
        if pv_started is None:
            continue
        pv_url = page_view.get("url")
        pv_video_id = _extract_youtube_video_id(pv_url)
        pv_is_youtube = _is_youtube_url(pv_url)
        for watch in watches:
            watch_started = watch["started_at_utc"]
            if watch_started is None:
                continue
            delta = abs((pv_started - watch_started).total_seconds())
            if delta > CORRELATION_YOUTUBE_WINDOW_SECONDS:
                continue

            watch_video_id = _extract_youtube_video_id(watch.get("url"))
            if pv_video_id and watch_video_id and pv_video_id == watch_video_id:
                correlations.append(
                    _correlation(
                        [page_view["event_id"], watch["event_id"]],
                        reason="same_youtube_video_url_within_120_seconds",
                        confidence=0.95,
                    )
                )
            elif pv_is_youtube and not pv_video_id:
                correlations.append(
                    _correlation(
                        [page_view["event_id"], watch["event_id"]],
                        reason="youtube_url_near_watch_event",
                        confidence=0.75,
                    )
                )
    return _with_sequential_ids(correlations)


def _correlation(
    event_ids: list[str],
    *,
    reason: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "correlation_id": "",
        "kind": "same_activity_candidate",
        "event_ids": event_ids,
        "confidence": confidence,
        "reason": reason,
    }


def _with_sequential_ids(
    correlations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """source pair ごとに ``corr_<tag>_<seq>`` の決定的 ID を振る。"""
    counters: dict[str, int] = {}
    for correlation in correlations:
        sources = sorted({eid.split(":", 1)[0] for eid in correlation["event_ids"]})
        tag = "_".join(sources)
        counters[tag] = counters.get(tag, 0) + 1
        correlation["correlation_id"] = f"corr_{tag}_{counters[tag]:03d}"
    return correlations


# ============================================================
# Gap
# ============================================================


def build_gaps(
    items: list[dict[str, Any]],
    *,
    gap_minutes: int | None,
    timezone: ZoneInfo,
) -> list[dict[str, Any]]:
    """隣接する観測イベント間で ``gap_minutes`` 以上の空きを gap として生成する。

    gap 判定は ``started_at_utc`` のみを使い、``ended_at_utc`` は使わない。
    「観測イベントがない」ことだけを意味し、長時間占有していたと断定しない。
    日の先頭・末尾の範囲外区間は gap にしない（前後両方に観測イベントが必要）。
    """
    if not gap_minutes or gap_minutes <= 0:
        return []

    ordered = [item for item in sort_items(items) if item["started_at_utc"]]
    if len(ordered) < 2:
        return []

    threshold = timedelta(minutes=gap_minutes)
    gaps: list[dict[str, Any]] = []
    for previous, following in zip(ordered, ordered[1:]):
        start = previous["started_at_utc"]
        end = following["started_at_utc"]
        if end - start < threshold:
            continue
        gaps.append(
            _gap(
                start,
                end,
                preceded_by=previous["event_id"],
                followed_by=following["event_id"],
                tz=timezone,
            )
        )
    return gaps


def _gap(
    start_utc: datetime,
    end_utc: datetime,
    *,
    preceded_by: str,
    followed_by: str,
    tz: ZoneInfo,
) -> dict[str, Any]:
    duration_minutes = int((end_utc - start_utc).total_seconds() // 60)
    return {
        "gap_id": (
            f"gap_{start_utc.astimezone(tz):%Y%m%d_%H%M}_{end_utc.astimezone(tz):%H%M}"
        ),
        "kind": "no_observed_events_gap",
        "start_utc": _iso_utc(start_utc),
        "end_utc": _iso_utc(end_utc),
        "start_local": _iso_local(start_utc, tz),
        "end_local": _iso_local(end_utc, tz),
        "duration_minutes": duration_minutes,
        "preceded_by_event_id": preceded_by,
        "followed_by_event_id": followed_by,
    }


# ============================================================
# raw_ref 制御 / local 時刻付与
# ============================================================


def apply_raw_refs(items: list[dict[str, Any]], include: bool) -> None:
    """``include=False`` のとき ``raw_ref`` を各 item から取り除く。"""
    if include:
        return
    for item in items:
        item.pop("raw_ref", None)


def finalize_item_times(items: list[dict[str, Any]], tz: ZoneInfo) -> None:
    """各 item の ``*_utc`` / ``*_local`` を ISO 文字列へ直列化する。

    gap / correlation の計算は datetime のまま行う必要があるため、
    それらが終わったあとの最終段階で呼ぶ。
    """
    for item in items:
        started = item.get("started_at_utc")
        ended = item.get("ended_at_utc")
        item["started_at_utc"] = _iso_utc(started)
        item["started_at_local"] = _iso_local(started, tz)
        item["ended_at_utc"] = _iso_utc(ended)
        item["ended_at_local"] = _iso_local(ended, tz)


# ============================================================
# Google Health 日次サマリ構築
# ============================================================


def _compose_google_health_summary(
    metrics: dict[str, Any],
    sleep_sessions: list[dict[str, Any]],
    date_local: date,
    tz: ZoneInfo,
) -> dict[str, Any] | None:
    """日次指標と睡眠セッションから Google Health 日次サマリを構築する。"""
    steps = _as_float(metrics.get("steps"))
    active_energy = _as_float(metrics.get("active_energy_burned"))
    resting_hr = _as_float(metrics.get("resting_heart_rate"))
    sleep_duration_seconds = _as_float(metrics.get("sleep_duration_seconds"))
    sleep = _build_sleep(sleep_sessions, sleep_duration_seconds, tz)

    has_any = (
        any(
            value is not None
            for value in (steps, active_energy, resting_hr, sleep_duration_seconds)
        )
        or sleep is not None
    )
    if not has_any:
        return None

    return {
        "date": date_local.isoformat(),
        "timezone": str(tz),
        "resting_heart_rate_bpm": _to_int(resting_hr),
        "sleep": sleep,
        "steps": _to_int(steps),
        "active_energy_kcal": _to_int(active_energy),
    }


def _build_sleep(
    sessions: list[dict[str, Any]],
    sleep_duration_seconds: float | None,
    tz: ZoneInfo,
) -> dict[str, Any] | None:
    """睡眠セッションと日次睡眠時間から sleep オブジェクトを構築する。"""
    valid = [
        s
        for s in sessions
        if _to_utc(s.get("started_at_utc")) and _to_utc(s.get("ended_at_utc"))
    ]
    if not valid and sleep_duration_seconds is None:
        return None

    asleep_minutes = (
        round(sleep_duration_seconds / 60)
        if sleep_duration_seconds is not None
        else None
    )
    if valid:
        starts = [_to_utc(s["started_at_utc"]) for s in valid]
        ends = [_to_utc(s["ended_at_utc"]) for s in valid]
        min_start = min(starts)
        max_end = max(ends)
        in_bed_minutes = round((max_end - min_start).total_seconds() / 60)
        return {
            "asleep_minutes": (
                asleep_minutes if asleep_minutes is not None else in_bed_minutes
            ),
            "in_bed_minutes": in_bed_minutes,
            "started_at_local": _iso_local(min_start, tz),
            "ended_at_local": _iso_local(max_end, tz),
        }
    return {"asleep_minutes": asleep_minutes}


# ============================================================
# 内部ヘルパ
# ============================================================


def _build_range(
    date_local: date,
    tz: ZoneInfo,
    utc_start: datetime,
    utc_end: datetime,
) -> dict[str, Any]:
    """top level の range オブジェクトを構築する。"""
    start_local = datetime(date_local.year, date_local.month, date_local.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return {
        "start_local": start_local.isoformat(),
        "end_local": end_local.isoformat(),
        "start_utc": _iso_utc(utc_start.replace(tzinfo=UTC)),
        "end_utc": _iso_utc(utc_end.replace(tzinfo=UTC)),
    }


def _event_id(source: str, kind: str, record_id: str) -> str:
    suffix = _EVENT_TYPE_SUFFIX[f"{source}:{kind}"]
    return f"{source}:{suffix}:{record_id}"


def _raw_ref(dataset_id: str, record_id: str, timestamp_column: str) -> dict[str, str]:
    return {
        "dataset_id": dataset_id,
        "record_id": record_id,
        "timestamp_column": timestamp_column,
    }


def _coverage_ok(event_count: int) -> dict[str, Any]:
    return {"included": True, "event_count": event_count, "status": "ok"}


def _coverage_excluded() -> dict[str, Any]:
    return {"included": False, "event_count": 0, "status": "excluded"}


def _coverage_not_available() -> dict[str, Any]:
    return {"included": True, "event_count": 0, "status": "not_available"}


def _to_utc(value: Any) -> datetime | None:
    """raw 行の時刻値を UTC aware datetime に正規化する。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    aware = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_local(dt: datetime | None, tz: ZoneInfo) -> str | None:
    if dt is None:
        return None
    aware = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return aware.astimezone(tz).isoformat()


def _duration_seconds(started: datetime | None, ended: datetime | None) -> int | None:
    if started is None or ended is None:
        return None
    delta = (ended - started).total_seconds()
    if delta <= 0:
        return None
    return int(delta)


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).netloc or None


_YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
)


def _is_youtube_url(url: str | None) -> bool:
    if not url:
        return False
    return (urlparse(url).netloc or "").lower() in _YOUTUBE_HOSTS


def _extract_youtube_video_id(url: str | None) -> str | None:
    """YouTube 動画 URL から video id を抽出する。抽出できない場合は None。"""
    if not url:
        return None
    parsed = urlparse(url)
    if (parsed.netloc or "").lower() not in _YOUTUBE_HOSTS:
        return None
    if parsed.netloc.lower() == "youtu.be":
        return parsed.path.strip("/") or None
    query = parse_qs(parsed.query)
    values = query.get("v")
    if values and values[0]:
        return values[0]
    return None


def _commit_title(message: str | None) -> str:
    """commit message の1行目を title とする。"""
    if not message:
        return "Commit"
    first_line = message.splitlines()[0].strip()
    return first_line or "Commit"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _to_int(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(value))
