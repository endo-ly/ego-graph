"""YouTubeスキーマ定義のテスト。"""

import duckdb

from pipelines.sources.google_activity.schema import YouTubeSchema


class TestYouTubeSchema:
    """YouTubeSchemaクラスのテスト。"""

    def test_raw_watch_history_sql_exists(self):
        """視聴履歴SQL定義が存在することを確認。"""
        assert hasattr(YouTubeSchema, "RAW_WATCH_HISTORY")
        assert len(YouTubeSchema.RAW_WATCH_HISTORY) > 0
        assert "CREATE OR REPLACE VIEW" in YouTubeSchema.RAW_WATCH_HISTORY.upper()
        assert "watch_history" in YouTubeSchema.RAW_WATCH_HISTORY.lower()

    def test_mart_videos_sql_exists(self):
        """動画マスターSQL定義が存在することを確認。"""
        assert hasattr(YouTubeSchema, "MART_VIDEOS")
        assert len(YouTubeSchema.MART_VIDEOS) > 0
        assert "CREATE OR REPLACE VIEW" in YouTubeSchema.MART_VIDEOS.upper()
        assert "videos" in YouTubeSchema.MART_VIDEOS.lower()

    def test_mart_channels_sql_exists(self):
        """チャンネルマスターSQL定義が存在することを確認。"""
        assert hasattr(YouTubeSchema, "MART_CHANNELS")
        assert len(YouTubeSchema.MART_CHANNELS) > 0
        assert "CREATE OR REPLACE VIEW" in YouTubeSchema.MART_CHANNELS.upper()
        assert "channels" in YouTubeSchema.MART_CHANNELS.lower()

    def test_initialize_mart_views_callable(self):
        """initialize_mart_viewsが呼び出し可能であることを確認。"""
        # Arrange: メモリ上のDuckDBコネクションを作成
        conn = duckdb.connect(":memory:")

        # Act: ビューを初期化（S3アクセスは失敗するが関数が動作することを確認）
        YouTubeSchema.initialize_mart_views(
            conn,
            watches_glob="s3://bucket/events/youtube/watch_history/*.parquet",
            videos_glob="s3://bucket/master/youtube/videos/*.parquet",
            channels_glob="s3://bucket/master/youtube/channels/*.parquet",
        )

        # Assert: ビュー定義が有効なSQLフォーマットであることを確認
        assert "CREATE OR REPLACE VIEW" in YouTubeSchema.RAW_WATCH_HISTORY
        assert "read_parquet" in YouTubeSchema.RAW_WATCH_HISTORY.lower()
        assert "{watches_glob}" in YouTubeSchema.RAW_WATCH_HISTORY

        assert "CREATE OR REPLACE VIEW" in YouTubeSchema.MART_VIDEOS
        assert "read_parquet" in YouTubeSchema.MART_VIDEOS.lower()
        assert "{videos_glob}" in YouTubeSchema.MART_VIDEOS

        assert "CREATE OR REPLACE VIEW" in YouTubeSchema.MART_CHANNELS
        assert "read_parquet" in YouTubeSchema.MART_CHANNELS.lower()
        assert "{channels_glob}" in YouTubeSchema.MART_CHANNELS

        # Cleanup
        conn.close()
