"""YouTubeデータ用の DuckDB スキーマ定義。"""

import logging

import duckdb

logger = logging.getLogger(__name__)


def _create_view_safely(
    conn: duckdb.DuckDBPyConnection, view_name: str, sql: str
) -> bool:
    """ビューを安全に作成する。失敗時は警告をログ出力する。

    Args:
        conn: DuckDB コネクション
        view_name: ビュー名（ログ用）
        sql: ビュー作成SQL

    Returns:
        作成に成功した場合は True
    """
    try:
        conn.execute(sql)
        logger.info("Created view %s", view_name)
        return True
    except Exception as e:
        logger.warning("Could not create %s: %s", view_name, e)
        return False


class YouTubeSchema:
    """YouTube データ用の DuckDB スキーマを管理する。"""

    # 視聴履歴ビュー定義（R2 Parquetファイルへのアクセス）
    RAW_WATCH_HISTORY = """
        CREATE OR REPLACE VIEW youtube.youtube_raw_watch_history AS
        SELECT
            watch_id,
            account_id,
            watched_at_utc,
            video_id,
            video_title,
            channel_id,
            channel_name,
            video_url,
            context
        FROM read_parquet('{watches_glob}', hive_partitioning = 1)
    """

    # 動画マスタービュー定義（R2 Parquetファイルへのアクセス）
    MART_VIDEOS = """
        CREATE OR REPLACE VIEW youtube.youtube_videos AS
        SELECT
            video_id,
            title,
            channel_id,
            channel_name,
            duration_seconds,
            view_count,
            like_count,
            comment_count,
            published_at,
            thumbnail_url,
            description,
            category_id,
            tags,
            updated_at
        FROM read_parquet('{videos_glob}', hive_partitioning = 1)
    """

    # チャンネルマスタービュー定義（R2 Parquetファイルへのアクセス）
    MART_CHANNELS = """
        CREATE OR REPLACE VIEW youtube.youtube_channels AS
        SELECT
            channel_id,
            channel_name,
            subscriber_count,
            video_count,
            view_count,
            published_at,
            thumbnail_url,
            description,
            country,
            updated_at
        FROM read_parquet('{channels_glob}', hive_partitioning = 1)
    """

    @staticmethod
    def initialize_mart_views(
        conn: duckdb.DuckDBPyConnection,
        watches_glob: str,
        videos_glob: str,
        channels_glob: str,
    ) -> None:
        """YouTubeデータのMartスキーマにビューを作成します。

        Args:
            conn: DuckDB コネクション
            watches_glob: 視聴履歴ParquetのS3グロブパターン
            videos_glob: 動画マスターParquetのS3グロブパターン
            channels_glob: チャンネルマスターParquetのS3グロブパターン
        """
        logger.info("Initializing YouTube Mart views...")

        # スキーマを作成
        conn.execute("CREATE SCHEMA IF NOT EXISTS youtube")

        # ビュー定義をフォーマットして作成
        view_definitions = [
            (
                "youtube_raw_watch_history",
                YouTubeSchema.RAW_WATCH_HISTORY.format(watches_glob=watches_glob),
            ),
            (
                "youtube_videos",
                YouTubeSchema.MART_VIDEOS.format(videos_glob=videos_glob),
            ),
            (
                "youtube_channels",
                YouTubeSchema.MART_CHANNELS.format(channels_glob=channels_glob),
            ),
        ]

        for view_name, sql in view_definitions:
            _create_view_safely(conn, view_name, sql)

        logger.info("YouTube Mart views initialized")
