"""Database/Queries層のテスト。"""

from datetime import date, timezone
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from backend.config import R2Config
from backend.infrastructure.database import (
    QueryParams,
    execute_query,
    get_listening_stats,
    get_parquet_path,
    get_top_tracks,
)
from backend.validators import to_utc_range


def _make_r2_config(bucket_name: str = "test-bucket") -> R2Config:
    return R2Config.model_construct(
        endpoint_url="https://test.r2.cloudflarestorage.com",
        access_key_id="test_key",
        secret_access_key=SecretStr("test_secret"),
        bucket_name=bucket_name,
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
        local_parquet_root=None,
    )


def _qp(**overrides):
    """テスト用 QueryParams ファクトリ（UTC で日付を解釈）。"""
    defaults: dict = dict(
        r2_config=_make_r2_config(),
        tz_name="UTC",
    )
    defaults.update(overrides)
    # Drop legacy fields no longer present on unified QueryParams
    defaults.pop("bucket", None)
    defaults.pop("events_path", None)
    defaults.pop("master_path", None)
    sd = defaults.pop("start_date")
    ed = defaults.pop("end_date")
    utc_start, utc_end = to_utc_range(sd, ed, timezone.utc)
    return QueryParams(
        start_date=sd,
        end_date=ed,
        utc_start=utc_start,
        utc_end=utc_end,
        **defaults,
    )


class TestGetParquetPath:
    """get_parquet_path のテスト。"""

    def test_generates_correct_path(self):
        """正しいS3パスパターンを生成。"""
        # Arrange: バケット名とプレフィックスを準備
        bucket = "my-bucket"
        prefix = "events/"

        # Act: S3パスを生成
        path = get_parquet_path(bucket, prefix)

        # Assert: 正しいパスパターンが生成されることを検証
        assert path == "s3://my-bucket/events/spotify/plays/**/*.parquet"

    def test_handles_different_bucket(self):
        """異なるバケット名で正しく生成。"""
        # Arrange: 異なるバケット名とプレフィックスを準備
        bucket = "test-bucket"
        prefix = "data/"

        # Act: S3パスを生成
        path = get_parquet_path(bucket, prefix)

        # Assert: 正しいパスパターンが生成されることを検証
        assert path == "s3://test-bucket/data/spotify/plays/**/*.parquet"


class TestExecuteQuery:
    """execute_query のテスト。"""

    def test_executes_simple_query(self, duckdb_conn):
        """シンプルなクエリを実行。"""
        # Arrange: DuckDB接続を準備（fixtureから提供）

        # Act: シンプルなSELECTクエリを実行
        result = execute_query(duckdb_conn, "SELECT 1 as value")

        # Assert: 結果が正しいことを検証
        assert len(result) == 1
        assert result[0]["value"] == 1

    def test_executes_query_with_params(self, duckdb_conn):
        """パラメータ付きクエリを実行。"""
        # Arrange: DuckDB接続を準備（fixtureから提供）

        # Act: パラメータを使用してクエリを実行
        result = execute_query(duckdb_conn, "SELECT ? as num", [42])

        # Assert: パラメータが正しく適用されることを検証
        assert result[0]["num"] == 42

    def test_returns_empty_list_for_no_results(self, duckdb_conn):
        """結果がない場合は空リストを返す。"""
        # Arrange: 空のテーブルを作成
        duckdb_conn.execute("CREATE TABLE empty_table (id INT)")

        # Act: 空のテーブルからSELECT
        result = execute_query(duckdb_conn, "SELECT * FROM empty_table")

        # Assert: 空リストが返されることを検証
        assert result == []

    def test_returns_list_of_dicts(self, duckdb_conn):
        """結果を辞書のリストで返す。"""
        # Arrange: テストテーブルを作成してデータを挿入
        duckdb_conn.execute("CREATE TABLE test_table (id INT, name VARCHAR)")
        duckdb_conn.execute("INSERT INTO test_table VALUES (1, 'Alice'), (2, 'Bob')")

        # Act: テーブルからデータを取得
        result = execute_query(duckdb_conn, "SELECT * FROM test_table ORDER BY id")

        # Assert: 辞書のリストとして正しく返されることを検証
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Alice"}
        assert result[1] == {"id": 2, "name": "Bob"}


class TestGetTopTracks:
    """get_top_tracks のテスト。"""

    def test_returns_top_tracks(self, duckdb_with_sample_data):
        """トップトラックを取得。"""
        # Arrange: get_top_tracksを使用してトップトラックを取得
        parquet_path = duckdb_with_sample_data.test_parquet_path

        # _resolve_partition_pathsをモックしてテスト用のparquetパスを返す
        with patch(
            "backend.infrastructure.database.queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            # Act: get_top_tracks関数を直接呼び出す
            params = _qp(
                conn=duckdb_with_sample_data,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_tracks(params, limit=5)

        # Assert: トップトラックが正しく取得されることを検証
        assert len(result) > 0
        # "Song A" (track_1) が3回再生されているので1位
        assert result[0]["track_name"] == "Song A"
        assert result[0]["play_count"] == 3
        assert "total_minutes" in result[0]

    def test_respects_limit_parameter(self, duckdb_with_sample_data):
        """limitパラメータを尊重。"""
        # Arrange: get_top_tracksを使用
        parquet_path = duckdb_with_sample_data.test_parquet_path

        # _resolve_partition_pathsをモックしてテスト用のparquetパスを返す
        with patch(
            "backend.infrastructure.database.queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            # Act: limit=2でトップトラックを取得
            params = _qp(
                conn=duckdb_with_sample_data,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_top_tracks(params, limit=2)

        # Assert: 最大2件までしか返されないことを検証
        assert len(result) <= 2

    def test_filters_by_date_range(self, duckdb_with_sample_data):
        """日付範囲でフィルタリング。"""
        # Arrange: get_top_tracksを使用
        parquet_path = duckdb_with_sample_data.test_parquet_path

        # _resolve_partition_pathsをモックしてテスト用のparquetパスを返す
        with patch(
            "backend.infrastructure.database.queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            # Act: 2024-01-01のデータのみ取得
            params = _qp(
                conn=duckdb_with_sample_data,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 1),
            )
            result = get_top_tracks(params, limit=10)

        # Assert: 2024-01-01には2件のレコードがあることを検証
        assert len(result) == 2


class TestGetListeningStats:
    """get_listening_stats のテスト。"""

    def test_aggregates_by_day(self, duckdb_with_sample_data):
        """日単位で集計。"""
        # Arrange: get_listening_statsを使用
        parquet_path = duckdb_with_sample_data.test_parquet_path

        # _resolve_partition_pathsをモックしてテスト用のparquetパスを返す
        with patch(
            "backend.infrastructure.database.queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            # Act: 日単位で統計情報を取得
            params = _qp(
                conn=duckdb_with_sample_data,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_listening_stats(params, granularity="day")

        # Assert: 3日分のデータが正しく集計されることを検証
        assert len(result) == 3  # 3日分
        assert result[0]["period"] == "2024-01-01"
        assert result[0]["track_count"] == 2

    def test_aggregates_by_month(self, duckdb_with_sample_data):
        """月単位で集計。"""
        # Arrange: get_listening_statsを使用
        parquet_path = duckdb_with_sample_data.test_parquet_path

        # _resolve_partition_pathsをモックしてテスト用のparquetパスを返す
        with patch(
            "backend.infrastructure.database.queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            # Act: 月単位で統計情報を取得
            params = _qp(
                conn=duckdb_with_sample_data,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            result = get_listening_stats(params, granularity="month")

        # Assert: 1ヶ月分のデータが正しく集計されることを検証
        assert len(result) == 1  # 1ヶ月分
        assert result[0]["period"] == "2024-01"
        assert result[0]["track_count"] == 5  # 全5件

    def test_invalid_granularity_raises_error(self, duckdb_with_sample_data):
        """無効な粒度でエラー発生。"""
        # Arrange: get_listening_statsを使用
        parquet_path = duckdb_with_sample_data.test_parquet_path

        # _resolve_partition_pathsをモックしてテスト用のparquetパスを返す
        with patch(
            "backend.infrastructure.database.queries._resolve_partition_paths",
            return_value=[parquet_path],
        ):
            # Act & Assert: 無効なgranularityでValueErrorが発生することを検証
            params = _qp(
                conn=duckdb_with_sample_data,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            with pytest.raises(ValueError, match="Invalid granularity"):
                get_listening_stats(params, granularity="invalid")

    def test_uses_iso_year_for_week_granularity(self, duckdb_with_sample_data):
        """週集計は ISO 年フォーマットを使う。"""
        parquet_path = duckdb_with_sample_data.test_parquet_path
        with (
            patch(
                "backend.infrastructure.database.queries._resolve_partition_paths",
                return_value=[parquet_path],
            ),
            patch(
                "backend.infrastructure.database.queries.execute_query",
                return_value=[],
            ) as mock_execute,
        ):
            params = _qp(
                conn=duckdb_with_sample_data,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )
            get_listening_stats(params, granularity="week")

        query = mock_execute.call_args.args[1]
        assert "%G-W%V" in query
