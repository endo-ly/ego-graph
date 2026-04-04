"""Spotify データ用の DuckDB ライター。"""

import logging
from datetime import timezone
from typing import Any

import duckdb

from .transform import transform_play_item

logger = logging.getLogger(__name__)

# 再生履歴用 SQL
_UPSERT_PLAYS_SQL = """
    INSERT OR REPLACE INTO raw.spotify_plays
    (play_id, played_at_utc, track_id, track_name,
     artist_ids, artist_names, album_id, album_name,
     ms_played, context_type, device_name)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# トラックマスター用 SQL
_UPSERT_TRACKS_SQL = """
    INSERT OR REPLACE INTO mart.spotify_tracks
    (track_id, name, artist_ids, artist_names,
     album_id, album_name, duration_ms, popularity)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


class SpotifyDuckDBWriter:
    """べき等な upsert で Spotify データを DuckDB に書き込む。"""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        """DuckDB コネクション付きでライターを初期化する。

        Args:
            conn: DuckDB コネクション
        """
        self.conn = conn

    def upsert_plays(self, items: list[dict[str, Any]]) -> int:
        """重複除去しながら再生履歴を挿入する。

        Args:
            items: Spotify API の生レスポンス項目 (recently_played)

        Returns:
            upsert したレコード数
        """
        if not items:
            return 0

        logger.info("Upserting %d play records", len(items))

        rows = []
        for item in items:
            event = transform_play_item(item)
            if not event:
                continue

            rows.append(
                (
                    event["play_id"],
                    event["played_at_utc"],
                    event["track_id"],
                    event["track_name"],
                    event["artist_ids"],
                    event["artist_names"],
                    event["album_id"],
                    event["album_name"],
                    event["ms_played"],
                    event["context_type"],
                    None,  # device_name: recently_played API には含まれない
                )
            )

        if rows:
            self.conn.executemany(_UPSERT_PLAYS_SQL, rows)

        logger.info("Successfully upserted %d plays", len(rows))
        return len(rows)

    def upsert_tracks(self, items: list[dict[str, Any]]) -> int:
        """楽曲マスタデータを挿入する。

        Args:
            items: Spotify API の生レスポンス項目 (recently_played)

        Returns:
            upsert したユニーク楽曲数
        """
        if not items:
            return 0

        logger.info("Upserting track master data")

        seen_ids: set[str] = set()
        rows = []

        for item in items:
            track = item.get("track") or {}
            track_id = track.get("id")
            if not track_id or track_id in seen_ids:
                continue

            seen_ids.add(track_id)
            rows.append(
                (
                    track_id,
                    track.get("name", "Unknown"),
                    [a.get("id") for a in track.get("artists", [])],
                    [a.get("name") for a in track.get("artists", [])],
                    track.get("album", {}).get("id"),
                    track.get("album", {}).get("name"),
                    track.get("duration_ms"),
                    track.get("popularity"),
                )
            )

        if rows:
            self.conn.executemany(_UPSERT_TRACKS_SQL, rows)

        logger.info("Successfully upserted %d tracks", len(rows))
        return len(rows)

    def get_stats(self) -> dict[str, Any]:
        """データベース統計情報を取得する。

        Returns:
            total_plays, total_tracks, latest_play を含む辞書
        """
        plays_result = self.conn.execute(
            "SELECT COUNT(*) FROM raw.spotify_plays"
        ).fetchone()
        tracks_result = self.conn.execute(
            "SELECT COUNT(*) FROM mart.spotify_tracks"
        ).fetchone()
        latest_result = self.conn.execute(
            "SELECT MAX(played_at_utc) FROM raw.spotify_plays"
        ).fetchone()

        latest_play = latest_result[0] if latest_result else None
        if latest_play and latest_play.tzinfo is None:
            latest_play = latest_play.replace(tzinfo=timezone.utc)

        return {
            "total_plays": plays_result[0] if plays_result else 0,
            "total_tracks": tracks_result[0] if tracks_result else 0,
            "latest_play": latest_play,
        }
