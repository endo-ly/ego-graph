"""R2上のSpotify再生履歴データを検証・確認するスクリプト。

総レコード数の確認と、最新50件の再生履歴を表示します。
DuckDBの httpfs 拡張を使用して、R2上のファイルを直接クエリします。

Usage:
    uv run python backend/scripts/verify_spotify_parquet.py
"""

import logging
import os
import sys

import duckdb
from tabulate import tabulate

# プロジェクトルートをパスに追加
sys.path.append(os.getcwd())

from backend.config import BackendConfig
from backend.infrastructure.database.parquet_paths import COMPACTED_ROOT

# ロギング設定
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def verify_r2_data():
    """R2上のParquetデータを検証し、最新の履歴を表示する。"""
    logger.info("🦆 Verifying EgoGraph R2 Data Lake...")

    try:
        config = BackendConfig.from_env()
    except Exception:
        logger.exception("Failed to load config")
        return

    if not config.r2:
        logger.error("R2 configuration is missing.")
        return

    r2_conf = config.r2
    conn = duckdb.connect(":memory:")

    try:
        # S3(R2) 設定の適用
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(
            """
            CREATE SECRET (
                TYPE S3,
                KEY_ID ?,
                SECRET ?,
                REGION 'auto',
                ENDPOINT ?,
                URL_STYLE 'path'
            );
            """,
            [
                r2_conf.access_key_id,
                r2_conf.secret_access_key.get_secret_value(),
                r2_conf.endpoint_url.replace("https://", ""),
            ],
        )

        # Parquetファイルのパスパターン
        parquet_url = (
            f"s3://{r2_conf.bucket_name}/{COMPACTED_ROOT}"
            "events/spotify/plays/**/*.parquet"
        )
        tracks_url = (
            f"s3://{r2_conf.bucket_name}/{COMPACTED_ROOT}"
            "master/spotify/tracks/**/*.parquet"
        )
        artists_url = (
            f"s3://{r2_conf.bucket_name}/{COMPACTED_ROOT}"
            "master/spotify/artists/**/*.parquet"
        )

        # 1. 総件数の確認
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM read_parquet(?)", [parquet_url]
            ).fetchone()[0]
            logger.info("✅ Connection successful. Total records in R2: %s", count)

            if count == 0:
                logger.info("ℹ️ R2 plays is empty. Run ingestion first.")
            else:
                # 2. 最新50件の曲名リスト表示 (シンプル表示)
                logger.info("\n📊 Latest 50 Tracks:")
                query_simple = """
                    SELECT track_name, artist_names[1] as artist, played_at_utc
                    FROM read_parquet(?)
                    ORDER BY played_at_utc DESC
                    LIMIT 50
                """
                df_simple = conn.execute(query_simple, [parquet_url]).df()

                # インデックスを1から振る
                df_simple.index = df_simple.index + 1
                print(
                    tabulate(
                        df_simple[["track_name", "artist"]],
                        headers=["#", "Track Name", "Artist"],
                        tablefmt="simple",
                    )
                )

                # 3. 直近5件の詳細表示 (デバッグ用)
                logger.info("\n🔍 Detailed View (Latest 5):")
                query_detail = """
                    SELECT played_at_utc, track_name, artist_names, album_name
                    FROM read_parquet(?)
                    ORDER BY played_at_utc DESC
                    LIMIT 5
                """
                df_detail = conn.execute(query_detail, [parquet_url]).df()
                print(tabulate(df_detail, headers="keys", tablefmt="simple_grid"))
        except duckdb.IOException as e:
            if "No files found" in str(e):
                logger.warning("⚠️ No Parquet files found for Spotify plays.")
            else:
                logger.error("❌ DuckDB IO Error: %s", e)

        # 4. トラックマスターの確認
        logger.info("\n" + "=" * 60)
        logger.info("🎧 Spotify Track Master (R2)")
        logger.info("=" * 60)

        try:
            track_count = conn.execute(
                "SELECT COUNT(*) FROM read_parquet(?, union_by_name=true)",
                [tracks_url],
            ).fetchone()[0]
            logger.info("✅ Total track master records in R2: %s", track_count)

            if track_count > 0:
                query_tracks = """
                    SELECT track_id, name, artist_names, preview_url, popularity
                    FROM read_parquet(?, union_by_name=true)
                    ORDER BY popularity DESC
                    LIMIT 10
                """
                df_tracks = conn.execute(query_tracks, [tracks_url]).df()
                print(tabulate(df_tracks, headers="keys", tablefmt="simple_grid"))
            else:
                logger.info("ℹ️ No track master data found.")
        except duckdb.IOException as e:
            if "No files found" in str(e):
                logger.warning("⚠️ No track master Parquet files found in R2.")
            else:
                logger.error("❌ DuckDB IO Error (tracks): %s", e)

        # 5. アーティストマスターの確認
        logger.info("\n" + "=" * 60)
        logger.info("🎤 Spotify Artist Master (R2)")
        logger.info("=" * 60)

        try:
            artist_count = conn.execute(
                "SELECT COUNT(*) FROM read_parquet(?, union_by_name=true)",
                [artists_url],
            ).fetchone()[0]
            logger.info("✅ Total artist master records in R2: %s", artist_count)

            if artist_count > 0:
                query_artists = """
                    SELECT artist_id, name, genres, popularity, followers_total
                    FROM read_parquet(?, union_by_name=true)
                    ORDER BY followers_total DESC
                    LIMIT 10
                """
                df_artists = conn.execute(query_artists, [artists_url]).df()
                print(tabulate(df_artists, headers="keys", tablefmt="simple_grid"))
            else:
                logger.info("ℹ️ No artist master data found.")
        except duckdb.IOException as e:
            if "No files found" in str(e):
                logger.warning("⚠️ No artist master Parquet files found in R2.")
            else:
                logger.error("❌ DuckDB IO Error (artists): %s", e)

    except duckdb.IOException as e:
        if "No files found" in str(e):
            logger.warning("⚠️ No Parquet files found in the specified path.")
        else:
            logger.error("❌ DuckDB IO Error: %s", e)
    except Exception as e:
        logger.error("❌ Unexpected Error: %s", e)
    finally:
        conn.close()


if __name__ == "__main__":
    verify_r2_data()
