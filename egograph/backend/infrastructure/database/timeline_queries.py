"""Daily Timeline 用の DuckDB クエリ。

各 source の compacted Parquet から指定期間（UTC range）の raw event を取得する。
正規化、ソート、correlation、gap 生成は Repository 層で行うため、
本モジュールは「UTC の raw 行」を最小限の列で返すことのみを責務とする。

時刻列は TIMESTAMP / TIMESTAMPTZ の混在に耐えるため
``make_timestamp(epoch_us(col))`` で UTC の naive TIMESTAMP に正規化して返す。
``epoch_us`` は絶対 UTC エポックを返すためセッションタイムゾーンに依存しない。
"""

from typing import Any

from dataset_catalog import datasets

from backend.infrastructure.database.parquet_paths import (
    build_dataset_glob,
    build_partition_paths,
)
from backend.infrastructure.database.query_params import QueryParams, execute_query

# TIMESTAMP / TIMESTAMPTZ を UTC naive に正規化する式。
_TS = "make_timestamp(epoch_us({col}))"

# GitHub compacted Parquet は timestamp 列が VARCHAR として保存されることがある。
# 既存の GitHub 個別クエリと同じく明示的に TIMESTAMP へ cast して扱う。
_GITHUB_TS = "{col}::TIMESTAMP"


def dataset_has_parquet(params: QueryParams, dataset) -> bool:
    """dataset の compacted Parquet が1件でも存在するか。

    dataset-wide availabilityではLocal mirrorの完全性を判定できないため、
    共通path resolverが返すR2 globを常に使用する。
    coverage の ``not_available`` 判定のために使う。
    """
    pattern = build_dataset_glob(params.r2_config, dataset)
    rows = params.conn.execute("SELECT COUNT(*) FROM glob(?)", (pattern,)).fetchone()
    return bool(rows and rows[0] > 0)


def fetch_spotify_plays(params: QueryParams) -> list[dict[str, Any]]:
    """Spotify 再生イベントを再生時刻 UTC 昇順で取得する。"""
    paths = build_partition_paths(
        params.r2_config,
        datasets.SPOTIFY_PLAYS,
        params.utc_start,
        params.utc_end,
    )
    sql = f"""
        SELECT
            play_id,
            {_TS.format(col="played_at_utc")} AS played_at_utc,
            track_id,
            track_name,
            artist_names,
            album_name,
            ms_played
        FROM read_parquet(?)
        WHERE {_TS.format(col="played_at_utc")} >= ?
          AND {_TS.format(col="played_at_utc")} < ?
        ORDER BY played_at_utc ASC
    """
    return execute_query(params.conn, sql, [paths, params.utc_start, params.utc_end])


def fetch_browser_page_views(params: QueryParams) -> list[dict[str, Any]]:
    """Browser History page view を開始時刻 UTC 昇順で取得する。"""
    paths = build_partition_paths(
        params.r2_config,
        datasets.BROWSER_HISTORY_PAGE_VIEWS,
        params.utc_start,
        params.utc_end,
    )
    sql = f"""
        SELECT
            page_view_id,
            {_TS.format(col="started_at_utc")} AS started_at_utc,
            {_TS.format(col="ended_at_utc")} AS ended_at_utc,
            url,
            title,
            browser,
            profile,
            transition,
            visit_span_count
        FROM read_parquet(?)
        WHERE {_TS.format(col="started_at_utc")} >= ?
          AND {_TS.format(col="started_at_utc")} < ?
        ORDER BY started_at_utc ASC
    """
    return execute_query(params.conn, sql, [paths, params.utc_start, params.utc_end])


def fetch_youtube_watch_events(params: QueryParams) -> list[dict[str, Any]]:
    """YouTube 視聴イベントを視聴時刻 UTC 昇順で取得する。

    timeline の正規化に必要なのは視聴イベント行そのもの（title/channel は
    watch_events に埋め込まれている）ため、master の結合は行わない。
    """
    paths = build_partition_paths(
        params.r2_config,
        datasets.YOUTUBE_WATCH_EVENTS,
        params.utc_start,
        params.utc_end,
    )
    sql = f"""
        SELECT
            watch_event_id,
            {_TS.format(col="watched_at_utc")} AS watched_at_utc,
            video_id,
            video_url,
            video_title,
            channel_id,
            channel_name,
            content_type,
            source,
            source_device
        FROM read_parquet(?)
        WHERE {_TS.format(col="watched_at_utc")} >= ?
          AND {_TS.format(col="watched_at_utc")} < ?
        ORDER BY watched_at_utc ASC
    """
    return execute_query(params.conn, sql, [paths, params.utc_start, params.utc_end])


def fetch_github_commits(params: QueryParams) -> list[dict[str, Any]]:
    """GitHub commit を commit 時刻 UTC 昇順で取得する。"""
    paths = build_partition_paths(
        params.r2_config,
        datasets.GITHUB_COMMITS,
        params.utc_start,
        params.utc_end,
    )
    sql = f"""
        SELECT
            commit_event_id,
            owner,
            repo,
            repo_full_name,
            sha,
            message,
            {_GITHUB_TS.format(col="committed_at_utc")} AS committed_at_utc,
            changed_files_count,
            additions,
            deletions
        FROM read_parquet(?)
        WHERE {_GITHUB_TS.format(col="committed_at_utc")} >= ?
          AND {_GITHUB_TS.format(col="committed_at_utc")} < ?
        ORDER BY committed_at_utc ASC
    """
    return execute_query(params.conn, sql, [paths, params.utc_start, params.utc_end])


def fetch_github_pull_requests(params: QueryParams) -> list[dict[str, Any]]:
    """GitHub Pull Request イベントを更新時刻 UTC 昇順で取得する。"""
    paths = build_partition_paths(
        params.r2_config,
        datasets.GITHUB_PULL_REQUESTS,
        params.utc_start,
        params.utc_end,
    )
    sql = f"""
        SELECT
            pr_event_id,
            owner,
            repo,
            repo_full_name,
            pr_number,
            action,
            state,
            is_merged,
            title,
            labels,
            {_GITHUB_TS.format(col="updated_at_utc")} AS updated_at_utc,
            additions,
            deletions,
            changed_files_count
        FROM read_parquet(?)
        WHERE {_GITHUB_TS.format(col="updated_at_utc")} >= ?
          AND {_GITHUB_TS.format(col="updated_at_utc")} < ?
        ORDER BY updated_at_utc ASC
    """
    return execute_query(params.conn, sql, [paths, params.utc_start, params.utc_end])


def fetch_google_health_daily_metrics(params: QueryParams) -> dict[str, Any]:
    """対象 local date の Google Health 日次指標を取得する。

    daily_metrics は long format（metric_name, value）なので、
    timeline が必要な指標のみ pivot して1行にまとめる。
    partition は local ``date`` の年月で決まるため、UTC range を使った
    build_partition_paths が対象月を含むように日付範囲を渡す。
    """
    sql = """
        WITH pivot_metrics AS (
            SELECT
                MAX(CASE WHEN metric_name = 'steps' THEN value END) AS steps,
                MAX(CASE
                    WHEN metric_name = 'active_energy_burned' THEN value
                END) AS active_energy_burned,
                MAX(CASE
                    WHEN metric_name IN (
                        'resting_heart_rate',
                        'daily_resting_heart_rate'
                    ) THEN value
                END) AS resting_heart_rate,
                MAX(CASE
                    WHEN metric_name = 'sleep_duration' THEN value
                END) AS sleep_duration_seconds
            FROM read_parquet(?)
            WHERE date = ?
        )
        SELECT * FROM pivot_metrics
    """
    paths = build_partition_paths(
        params.r2_config,
        datasets.GOOGLE_HEALTH_DAILY_METRICS,
        params.utc_start,
        params.utc_end,
    )
    rows = execute_query(params.conn, sql, [paths, params.start_date])
    return rows[0] if rows else {}


def fetch_google_health_sleep_sessions(params: QueryParams) -> list[dict[str, Any]]:
    """対象 local date に帰属する睡眠セッションを取得する。

    睡眠は「起床日の」指標として扱うため、``ended_at_utc`` を local date に
    変換した結果が対象日と一致するセッションを取得する。睡眠は前夜に始まるため、
    UTC range（対象 local date の UTC 窓）は前月 partition も自然に含む。
    """
    sql = f"""
        SELECT
            {_TS.format(col="started_at_utc")} AS started_at_utc,
            {_TS.format(col="ended_at_utc")} AS ended_at_utc,
            duration_seconds,
            session_type
        FROM read_parquet(?)
        WHERE data_type = 'sleep'
          AND (({_TS.format(col="ended_at_utc")} AT TIME ZONE 'UTC')
                AT TIME ZONE ?)::DATE = ?
        ORDER BY started_at_utc ASC
    """
    paths = build_partition_paths(
        params.r2_config,
        datasets.GOOGLE_HEALTH_SESSIONS,
        params.utc_start,
        params.utc_end,
    )
    return execute_query(params.conn, sql, [paths, params.tz_name, params.start_date])
