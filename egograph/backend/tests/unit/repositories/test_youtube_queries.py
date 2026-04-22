"""YouTube クエリ層のテスト。"""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from backend.infrastructure.database.youtube_queries import (
    DEFAULT_WATCH_EVENTS_LIMIT,
    YouTubeQueryParams,
    _generate_partition_paths,
    _resolve_watch_event_paths,
    execute_query,
    get_channels_parquet_path,
    get_top_channels,
    get_top_videos,
    get_videos_parquet_path,
    get_watch_events,
    get_watch_events_parquet_path,
    get_watching_stats,
)
from backend.tests.fixtures.youtube import patch_youtube_paths


class TestYouTubeQueryParams:
    """YouTubeQueryParams dataclassのテスト。"""

    def test_creates_params(self, duckdb_conn):
        """YouTubeQueryParamsを作成。"""
        # Arrange & Act
        params = YouTubeQueryParams(
            conn=duckdb_conn,
            bucket="test-bucket",
            events_path="events/",
            master_path="master/",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        # Assert
        assert params.bucket == "test-bucket"
        assert params.events_path == "events/"
        assert params.start_date == date(2024, 1, 1)
        assert params.end_date == date(2024, 1, 31)


class TestGetParquetPaths:
    """Parquetパス生成関数のテスト。"""

    def test_get_watch_events_parquet_path(self):
        """視聴イベントのS3パスパターンを生成。"""
        # Arrange & Act
        path = get_watch_events_parquet_path("my-bucket", "events/")

        # Assert
        assert path == "s3://my-bucket/events/youtube/watch_events/**/*.parquet"

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


class TestGeneratePartitionPaths:
    """_generate_partition_paths のテスト。"""

    def test_generates_single_month_path(self):
        """1ヶ月分のパスを生成。"""
        # Arrange
        bucket = "my-bucket"
        events_path = "events/"
        start = date(2024, 1, 1)
        end = date(2024, 1, 31)

        # Act
        paths = _generate_partition_paths(bucket, events_path, start, end)

        # Assert
        assert len(paths) == 1
        assert (
            paths[0]
            == "s3://my-bucket/events/youtube/watch_events/year=2024/month=01/**/*.parquet"
        )

    def test_generates_multiple_month_paths(self):
        """複数月のパスを生成。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "data/"
        start = date(2024, 11, 15)
        end = date(2025, 1, 15)

        # Act
        paths = _generate_partition_paths(bucket, events_path, start, end)

        # Assert
        assert len(paths) == 3
        assert (
            paths[0]
            == "s3://test-bucket/data/youtube/watch_events/year=2024/month=11/**/*.parquet"
        )
        assert (
            paths[1]
            == "s3://test-bucket/data/youtube/watch_events/year=2024/month=12/**/*.parquet"
        )
        assert (
            paths[2]
            == "s3://test-bucket/data/youtube/watch_events/year=2025/month=01/**/*.parquet"
        )

    def test_handles_year_boundary(self):
        """年をまたぐ期間を正しく処理。"""
        # Arrange
        bucket = "bucket"
        events_path = "events/"
        start = date(2023, 12, 1)
        end = date(2024, 1, 31)

        # Act
        paths = _generate_partition_paths(bucket, events_path, start, end)

        # Assert
        assert len(paths) == 2
        assert "year=2023/month=12" in paths[0]
        assert "year=2024/month=01" in paths[1]


class TestResolveWatchEventPaths:
    """_resolve_watch_event_paths のテスト。"""

    def test_falls_back_to_dataset_glob_when_no_partition_matches(self):
        """月パーティションが未作成なら dataset glob にフォールバック。"""
        conn = Mock()
        execute_result = Mock()
        execute_result.fetchone.return_value = (0,)
        conn.execute.return_value = execute_result
        params = YouTubeQueryParams(
            conn=conn,
            bucket="test-bucket",
            events_path="events/",
            master_path="master/",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        with (
            patch(
                "backend.infrastructure.database.youtube_queries._generate_partition_paths",
                return_value=[
                    "s3://test/events/youtube/watch_events/year=2024/month=01/**/*.parquet"
                ],
            ),
            patch(
                "backend.infrastructure.database.youtube_queries.get_watch_events_parquet_path",
                return_value="s3://test/events/youtube/watch_events/**/*.parquet",
            ),
        ):
            paths = _resolve_watch_event_paths(params)

        assert paths == ["s3://test/events/youtube/watch_events/**/*.parquet"]


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
            params = YouTubeQueryParams(
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
        assert "watched_at_utc" in result[0]
        assert "video_title" in result[0]

    def test_filters_by_date_range(self, youtube_with_sample_data):
        """日付範囲でフィルタリング。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act: 2024-01-01のデータのみ取得
            params = YouTubeQueryParams(
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

    def test_respects_limit_parameter(self, youtube_with_sample_data):
        """limitパラメータを尊重。"""
        # Arrange
        bucket = "test-bucket"
        events_path = "events/"
        with patch_youtube_paths(youtube_with_sample_data):
            # Act: limit=2で取得
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
            params = YouTubeQueryParams(
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
