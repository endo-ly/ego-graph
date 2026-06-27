"""YouTube クエリ層のテスト。"""

from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from dataset_catalog import datasets

from backend.config import R2Config
from backend.infrastructure.database.parquet_paths import build_partition_paths
from backend.infrastructure.database.query_params import QueryParams
from backend.infrastructure.database.youtube_queries import (
    DEFAULT_WATCH_EVENTS_LIMIT,
    _build_enriched_cte,
    _parquet_file_exists,
    _resolve_watch_event_paths,
    execute_query,
    get_channels_parquet_path,
    get_top_channels,
    get_top_videos,
    get_videos_parquet_path,
    get_watch_events,
    get_watching_stats,
)
from backend.tests.fixtures.youtube import patch_youtube_paths
from backend.validators import to_utc_range


def _yqp(**overrides):
    """テスト用 QueryParams ファクトリ。"""
    defaults = dict(
        tz_name="UTC",
    )
    defaults.update(overrides)
    sd = defaults.pop("start_date")
    ed = defaults.pop("end_date")
    # r2_config が指定されていなければ、個別フィールドから構築
    if "r2_config" not in defaults:
        defaults["r2_config"] = R2Config.model_construct(
            endpoint_url="https://test.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name=defaults.pop("bucket", "test-bucket"),
            raw_path="raw/",
            events_path=defaults.pop("events_path", "events/"),
            master_path=defaults.pop("master_path", "master/"),
            local_parquet_root=None,
        )
    utc_start, utc_end = to_utc_range(sd, ed, timezone.utc)
    return QueryParams(
        start_date=sd,
        end_date=ed,
        utc_start=utc_start,
        utc_end=utc_end,
        **defaults,
    )


class TestQueryParams:
    """QueryParams dataclassのテスト。"""

    def test_creates_params(self, duckdb_conn):
        """QueryParamsを作成。"""
        # Arrange & Act
        params = _yqp(
            conn=duckdb_conn,
            r2_config=R2Config.model_construct(
                endpoint_url="https://test.r2.cloudflarestorage.com",
                access_key_id="test_key",
                secret_access_key="test_secret",
                bucket_name="test-bucket",
                raw_path="raw/",
                events_path="events/",
                master_path="master/",
                local_parquet_root=None,
            ),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        # Assert
        assert params.r2_config.bucket_name == "test-bucket"
        assert params.start_date == date(2024, 1, 1)
        assert params.end_date == date(2024, 1, 31)


class TestGetParquetPaths:
    """Parquetパス生成関数のテスト。"""

    def test_get_videos_parquet_path(self):
        """動画マスターのS3パスパターンを生成。"""
        # Arrange & Act
        path = get_videos_parquet_path("my-bucket", "master/")

        # Assert
        assert path == "s3://my-bucket/master/youtube/videos/data.parquet"

    def test_get_channels_parquet_path(self):
        """チャンネルマスターのS3パスパターンを生成。"""
        # Arrange & Act
        path = get_channels_parquet_path("my-bucket", "master/")

        # Assert
        assert path == "s3://my-bucket/master/youtube/channels/data.parquet"


class TestBuildPartitionPaths:
    """build_partition_paths のテスト。"""

    def test_generates_single_month_path(self, mock_r2_config):
        """1ヶ月分のパスを生成。"""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 2, 1)

        paths = build_partition_paths(
            mock_r2_config,
            datasets.YOUTUBE_WATCH_EVENTS,
            start,
            end,
        )

        assert len(paths) == 2  # Jan + Feb
        assert "year=2024/month=01" in paths[0]

    def test_generates_multiple_month_paths(self, mock_r2_config):
        """複数月のパスを生成。"""
        start = datetime(2024, 11, 15)
        end = datetime(2025, 2, 1)

        paths = build_partition_paths(
            mock_r2_config,
            datasets.YOUTUBE_WATCH_EVENTS,
            start,
            end,
        )

        assert len(paths) == 4

    def test_handles_year_boundary(self, mock_r2_config):
        """年をまたぐ期間を正しく処理。"""
        start = datetime(2023, 12, 1)
        end = datetime(2024, 2, 1)

        paths = build_partition_paths(
            mock_r2_config,
            datasets.YOUTUBE_WATCH_EVENTS,
            start,
            end,
        )

        assert len(paths) == 3
        assert "year=2023/month=12" in paths[0]
        assert "year=2024/month=01" in paths[1]


class TestResolveWatchEventPaths:
    """_resolve_watch_event_paths のテスト。"""

    def test_delegates_to_build_partition_paths(self, mock_r2_config):
        """build_partition_paths に委譲する。"""
        params = _yqp(
            conn=Mock(),
            r2_config=mock_r2_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        expected = [
            "s3://test/events/youtube/watch_events/year=2024/month=01/**/*.parquet"
        ]
        with patch(
            "backend.infrastructure.database.youtube_queries.build_partition_paths",
            return_value=expected,
        ) as mock_func:
            paths = _resolve_watch_event_paths(params)

        assert paths == expected
        mock_func.assert_called_once_with(
            mock_r2_config,
            datasets.YOUTUBE_WATCH_EVENTS,
            utc_start=params.utc_start,
            utc_end=params.utc_end,
        )


class TestExecuteQuery:
    """execute_query のテスト。"""

    def test_executes_simple_query(self, duckdb_conn):
        """シンプルなクエリを実行。"""
        # Arrange & Act
        result = execute_query(duckdb_conn, "SELECT 1 as value")

        # Assert
        assert len(result) == 1
        assert result[0]["value"] == 1

    def test_executes_query_with_params(self, duckdb_conn):
        """パラメータ付きクエリを実行。"""
        # Arrange & Act
        result = execute_query(duckdb_conn, "SELECT ? as num", [42])

        # Assert
        assert result[0]["num"] == 42

    def test_returns_empty_list_for_no_results(self, duckdb_conn):
        """結果がない場合は空リストを返す。"""
        # Arrange
        duckdb_conn.execute("CREATE TABLE empty_table (id INT)")

        # Act
        result = execute_query(duckdb_conn, "SELECT * FROM empty_table")

        # Assert
        assert result == []

    def test_returns_list_of_dicts(self, duckdb_conn):
        """結果を辞書のリストで返す。"""
        # Arrange
        duckdb_conn.execute("CREATE TABLE test_table (id INT, name VARCHAR)")
        duckdb_conn.execute("INSERT INTO test_table VALUES (1, 'Alice'), (2, 'Bob')")

        # Act
        result = execute_query(duckdb_conn, "SELECT * FROM test_table ORDER BY id")

        # Assert
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Alice"}
        assert result[1] == {"id": 2, "name": "Bob"}


class TestGetWatchEvents:
    """get_watch_events のテスト。"""

    def test_returns_watch_events(self, youtube_with_sample_data):
        """視聴イベントを取得。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_watch_events(params)

        # Assert
        assert len(result) > 0
        assert "watch_event_id" in result[0]
        assert "watched_at" in result[0]
        assert "video_title" in result[0]

    def test_filters_by_date_range(self, youtube_with_sample_data):
        """日付範囲でフィルタリング。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act: 2024-01-01のデータのみ取得
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 1),
            )
            result = get_watch_events(params)

        # Assert: 2024-01-01には2件のレコードがある
        assert len(result) == 2

    def test_filters_timestamptz_as_utc_when_duckdb_session_timezone_differs(
        self, duckdb_conn, tmp_path
    ):
        """TIMESTAMPTZ列でもUTC境界でフィルタリングする。"""
        # Arrange
        watch_events_path = tmp_path / "watch_events.parquet"
        missing_videos_path = tmp_path / "missing_videos.parquet"
        missing_channels_path = tmp_path / "missing_channels.parquet"
        pd.DataFrame(
            {
                "watch_event_id": ["we_1", "we_2"],
                "watched_at_utc": pd.to_datetime(
                    ["2026-06-23T00:30:00Z", "2026-06-23T01:00:00Z"],
                    utc=True,
                ),
                "video_id": ["video_1", "video_2"],
                "video_url": [
                    "https://youtube.com/watch?v=video_1",
                    "https://youtube.com/watch?v=video_2",
                ],
                "video_title": ["Video A", "Video B"],
                "channel_id": ["channel_1", "channel_2"],
                "channel_name": ["Channel X", "Channel Y"],
                "content_type": ["video", "video"],
            }
        ).to_parquet(watch_events_path)
        duckdb_conn.execute("SET TimeZone='America/Los_Angeles'")

        with (
            patch(
                "backend.infrastructure.database.youtube_queries.build_partition_paths",
                return_value=[str(watch_events_path)],
            ),
            patch(
                "backend.infrastructure.database.youtube_queries.get_videos_parquet_path",
                return_value=str(missing_videos_path),
            ),
            patch(
                "backend.infrastructure.database.youtube_queries.get_channels_parquet_path",
                return_value=str(missing_channels_path),
            ),
        ):
            params = _yqp(
                conn=duckdb_conn,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2026, 6, 23),
                end_date=date(2026, 6, 23),
            )

            # Act
            result = get_watch_events(params)

        # Assert
        assert {row["watch_event_id"] for row in result} == {"we_1", "we_2"}

    def test_respects_limit_parameter(self, youtube_with_sample_data):
        """limitパラメータを尊重。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act: limit=2で取得
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_watch_events(params, limit=2)

        # Assert
        assert len(result) <= 2

    def test_applies_default_limit_when_limit_is_none(self, youtube_with_sample_data):
        """limit未指定でも bounded query として実行する。"""
        with patch_youtube_paths(youtube_with_sample_data):
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            with patch(
                "backend.infrastructure.database.youtube_queries.execute_query",
                return_value=[],
            ) as mock_execute:
                get_watch_events(params)

        query = mock_execute.call_args.args[1]
        query_params = mock_execute.call_args.args[2]
        assert f"LIMIT COALESCE(?, {DEFAULT_WATCH_EVENTS_LIMIT})" in query
        assert query_params[-1] is None


class TestGetWatchingStats:
    """get_watching_stats のテスト。"""

    def test_aggregates_by_day(self, youtube_with_sample_data):
        """日単位で集計。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_watching_stats(params, granularity="day")

        # Assert: 3日分のデータが正しく集計される
        assert len(result) == 3
        assert result[0]["period"] == "2024-01-01"
        assert result[0]["watch_event_count"] == 2
        assert "unique_video_count" in result[0]
        assert "unique_channel_count" in result[0]

    def test_aggregates_by_month(self, youtube_with_sample_data):
        """月単位で集計。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_watching_stats(params, granularity="month")

        # Assert: 1ヶ月分のデータが正しく集計される
        assert len(result) == 1
        assert result[0]["period"] == "2024-01"
        assert result[0]["watch_event_count"] == 5

    def test_invalid_granularity_raises_error(self, youtube_with_sample_data):
        """無効な粒度でエラー発生。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            # Act & Assert
            with pytest.raises(ValueError, match="Invalid granularity"):
                get_watching_stats(params, granularity="invalid")

    def test_uses_iso_year_for_week_granularity(self, youtube_with_sample_data):
        """週集計は ISO 年フォーマットを使う。"""
        with patch_youtube_paths(youtube_with_sample_data):
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            with patch(
                "backend.infrastructure.database.youtube_queries.execute_query",
                return_value=[],
            ) as mock_execute:
                get_watching_stats(params, granularity="week")

        query = mock_execute.call_args.args[1]
        assert "%G-W%V" in query


class TestGetTopVideos:
    """get_top_videos のテスト。"""

    def test_returns_top_videos(self, youtube_with_sample_data):
        """トップ動画を取得。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_videos(params)

        # Assert
        assert len(result) > 0
        assert "video_id" in result[0]
        assert "video_title" in result[0]
        assert "watch_event_count" in result[0]

    def test_respects_limit_parameter(self, youtube_with_sample_data):
        """limitパラメータを尊重。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act: limit=2で取得
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_videos(params, limit=2)

        # Assert
        assert len(result) <= 2

    def test_orders_by_watch_event_count(self, youtube_with_sample_data):
        """視聴イベント数降順でソート。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_videos(params)

        # Assert: 視聴イベント数降順でソートされている
        for i in range(len(result) - 1):
            assert result[i]["watch_event_count"] >= result[i + 1]["watch_event_count"]


class TestGetTopChannels:
    """get_top_channels のテスト。"""

    def test_returns_top_channels(self, youtube_with_sample_data):
        """トップチャンネルを取得。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_channels(params)

        # Assert
        assert len(result) > 0
        assert "channel_id" in result[0]
        assert "channel_name" in result[0]
        assert "watch_event_count" in result[0]
        assert "unique_video_count" in result[0]

    def test_respects_limit_parameter(self, youtube_with_sample_data):
        """limitパラメータを尊重。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act: limit=2で取得
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_channels(params, limit=2)

        # Assert
        assert len(result) <= 2

    def test_orders_by_watch_event_count(self, youtube_with_sample_data):
        """視聴イベント数降順でソート。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act
            params = _yqp(
                conn=youtube_with_sample_data,
                bucket=bucket,
                events_path=events_path,
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_channels(params)

        # Assert: 視聴イベント数降順でソートされている
        for i in range(len(result) - 1):
            assert result[i]["watch_event_count"] >= result[i + 1]["watch_event_count"]


class TestParquetFileExists:
    """_parquet_file_exists のテスト。"""

    def test_returns_true_for_existing_file(self, duckdb_conn, tmp_path):
        """存在するファイルに対して True を返す。"""
        # Arrange
        parquet_path = tmp_path / "exists.parquet"
        pd.DataFrame({"id": [1]}).to_parquet(parquet_path)

        # Act
        result = _parquet_file_exists(duckdb_conn, str(parquet_path))

        # Assert
        assert result is True

    def test_returns_false_for_missing_file(self, duckdb_conn, tmp_path):
        """存在しないファイルに対して False を返す。"""
        # Act
        result = _parquet_file_exists(
            duckdb_conn, str(tmp_path / "nonexistent.parquet")
        )

        # Assert
        assert result is False

    def test_checks_parent_glob_instead_of_direct_path(self):
        """完全パス glob の誤検出を避けるため、親ディレクトリ列挙で確認する。"""
        conn = Mock()
        execute_result = Mock()
        execute_result.fetchone.return_value = (0,)
        conn.execute.return_value = execute_result

        path = "s3://egograph/master/youtube/videos/data.parquet"

        result = _parquet_file_exists(conn, path)

        assert result is False
        conn.execute.assert_called_once_with(
            "SELECT COUNT(*) FROM glob(?) WHERE file = ?",
            ["s3://egograph/master/youtube/videos/*", path],
        )


class TestMissingMasterData:
    """マスターデータ不存在時の graceful degradation テスト。"""

    def test_get_watch_events_without_master(self, youtube_without_master_data):
        """マスターなしでも watch events を取得できる。"""
        with patch_youtube_paths(youtube_without_master_data):
            params = _yqp(
                conn=youtube_without_master_data,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_watch_events(params)

        # Assert: watch events の件数はそのまま返る
        assert len(result) == 5
        assert "watch_event_id" in result[0]
        # COALESCE で watch events 側の値が使われる
        assert result[0]["video_title"] == "Video A"
        assert result[0]["channel_name"] == "Channel X"

    def test_get_watching_stats_without_master(self, youtube_without_master_data):
        """マスターなしでも視聴統計を取得できる。"""
        with patch_youtube_paths(youtube_without_master_data):
            params = _yqp(
                conn=youtube_without_master_data,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_watching_stats(params, granularity="day")

        # Assert: 3日分の統計が返る
        assert len(result) == 3
        assert result[0]["watch_event_count"] == 2

    def test_get_top_videos_without_master(self, youtube_without_master_data):
        """マスターなしでもトップ動画を取得できる。"""
        with patch_youtube_paths(youtube_without_master_data):
            params = _yqp(
                conn=youtube_without_master_data,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_videos(params)

        # Assert: video_1 が最も再生回数が多い
        assert len(result) > 0
        assert result[0]["video_id"] == "video_1"
        assert result[0]["watch_event_count"] == 3
        # COALESCE で watch events 側のタイトルが使われる
        assert result[0]["video_title"] == "Video A"

    def test_get_top_channels_without_master(self, youtube_without_master_data):
        """マスターなしでもトップチャンネルを取得できる。"""
        with patch_youtube_paths(youtube_without_master_data):
            params = _yqp(
                conn=youtube_without_master_data,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_channels(params)

        # Assert: channel_1 が最も再生回数が多い
        assert len(result) > 0
        assert result[0]["channel_id"] == "channel_1"
        assert result[0]["watch_event_count"] == 3

    def test_build_enriched_cte_without_master(self, youtube_without_master_data):
        """マスターなしの場合、CTE に read_parquet パラメータが含まれない。"""
        with patch_youtube_paths(youtube_without_master_data):
            params = _yqp(
                conn=youtube_without_master_data,
                bucket="test-bucket",
                events_path="events/",
                master_path="master/",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            ctes, sql_params = _build_enriched_cte(params)

        # Assert: CTE に空テーブル定義が含まれる
        assert "WHERE 1=0" in ctes
        assert "latest_videos" in ctes
        assert "latest_channels" in ctes
        # read_parquet は watch events の分だけ（マスター分は含まれない）
        assert "read_parquet" in ctes
        # パラメータは watch events のパス + 日付のみ
        assert len(sql_params) == 3  # paths, start_date, end_date
