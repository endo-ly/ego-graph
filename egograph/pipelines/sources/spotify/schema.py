"""Spotify データ用の DuckDB スキーマ定義。"""

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# エンリッチドビューのSQL定義
_ENRICHED_VIEW_SQL = """
    CREATE OR REPLACE VIEW mart.spotify_plays_enriched AS
    SELECT
        p.play_id,
        p.played_at_utc,
        p.track_id,
        p.track_name,
        p.artist_ids,
        p.artist_names,
        p.album_id,
        p.album_name,
        p.ms_played,
        p.context_type,
        p.popularity AS play_popularity,
        t.duration_ms,
        t.popularity AS track_popularity,
        t.explicit,
        t.preview_url,
        a.artist_id AS primary_artist_id,
        a.name AS primary_artist_name,
        a.genres,
        a.popularity AS artist_popularity,
        a.followers_total
    FROM mart.spotify_plays p
    LEFT JOIN mart.spotify_tracks t
        ON p.track_id = t.track_id
    LEFT JOIN mart.spotify_artists a
        ON p.artist_ids[1] = a.artist_id
"""


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


class SpotifySchema:
    """Spotify データ用の DuckDB スキーマを管理する。"""

    RAW_PLAYS_TABLE = """
        CREATE TABLE IF NOT EXISTS raw.spotify_plays (
            play_id VARCHAR PRIMARY KEY,
            played_at_utc TIMESTAMP NOT NULL,
            track_id VARCHAR NOT NULL,
            track_name VARCHAR NOT NULL,
            artist_ids VARCHAR[],
            artist_names VARCHAR[],
            album_id VARCHAR,
            album_name VARCHAR,
            ms_played INTEGER,
            context_type VARCHAR,
            device_name VARCHAR,
            inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    MART_TRACKS_TABLE = """
        CREATE TABLE IF NOT EXISTS mart.spotify_tracks (
            track_id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            artist_ids VARCHAR[],
            artist_names VARCHAR[],
            album_id VARCHAR,
            album_name VARCHAR,
            duration_ms INTEGER,
            popularity INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    @staticmethod
    def initialize_db(db_path: str) -> duckdb.DuckDBPyConnection:
        """スキーマ付きで DuckDB を初期化する。

        Args:
            db_path: DuckDB データベースファイルへのパス

        Returns:
            DuckDB コネクション
        """
        logger.info("Initializing DuckDB at %s", db_path)

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(db_path)

        conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
        conn.execute("CREATE SCHEMA IF NOT EXISTS mart")

        conn.execute(SpotifySchema.RAW_PLAYS_TABLE)
        conn.execute(SpotifySchema.MART_TRACKS_TABLE)

        logger.info("Schema initialized successfully")
        return conn

    @staticmethod
    def create_indexes(conn: duckdb.DuckDBPyConnection) -> None:
        """パフォーマンス向上用のインデックスを作成する。

        Args:
            conn: DuckDB コネクション
        """
        logger.info("Creating indexes...")

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_plays_time
            ON raw.spotify_plays(played_at_utc DESC)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_plays_track
            ON raw.spotify_plays(track_id)
        """)

        logger.info("Indexes created")

    @staticmethod
    def initialize_mart_views(
        conn: duckdb.DuckDBPyConnection,
        plays_glob: str,
        tracks_glob: str,
        artists_glob: str,
    ) -> None:
        """MartスキーマにSpotifyのビューを作成します。

        Args:
            conn: DuckDB コネクション
            plays_glob: 再生履歴ParquetのS3グロブパターン
            tracks_glob: トラックマスターParquetのS3グロブパターン
            artists_glob: アーティストマスターParquetのS3グロブパターン
        """
        logger.info("Initializing Spotify Mart views...")

        conn.execute("CREATE SCHEMA IF NOT EXISTS mart")

        view_definitions = [
            (
                "mart.spotify_plays",
                f"CREATE OR REPLACE VIEW mart.spotify_plays AS "
                f"SELECT * FROM read_parquet('{plays_glob}', hive_partitioning = 1)",
            ),
            (
                "mart.spotify_tracks",
                f"CREATE OR REPLACE VIEW mart.spotify_tracks AS "
                f"SELECT * FROM read_parquet('{tracks_glob}', hive_partitioning = 1)",
            ),
            (
                "mart.spotify_artists",
                f"CREATE OR REPLACE VIEW mart.spotify_artists AS "
                f"SELECT * FROM read_parquet('{artists_glob}', hive_partitioning = 1)",
            ),
        ]

        for view_name, sql in view_definitions:
            _create_view_safely(conn, view_name, sql)

        _create_view_safely(conn, "mart.spotify_plays_enriched", _ENRICHED_VIEW_SQL)
