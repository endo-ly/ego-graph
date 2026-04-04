"""Spotify生データを分析用スキーマに変換するモジュール。"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _extract_artist_ids(track: dict[str, Any]) -> list[str | None]:
    """トラックからアーティストIDリストを抽出する。"""
    return [a.get("id") for a in track.get("artists", [])]


def _extract_artist_names(track: dict[str, Any]) -> list[str | None]:
    """トラックからアーティスト名リストを抽出する。"""
    return [a.get("name") for a in track.get("artists", [])]


def _get_album_field(track: dict[str, Any], field: str) -> str | None:
    """トラックのアルバム情報から指定フィールドを取得する。"""
    return track.get("album", {}).get(field)


def _generate_play_id(played_at: str, track_id: str) -> str:
    """再生履歴のユニークIDを生成する。"""
    if played_at and track_id:
        return f"{played_at}_{track_id}"
    return str(uuid4())


def transform_play_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """単一の再生履歴アイテムをイベント形式に変換する。

    Args:
        item: Spotify API (recently_played) の単一 item

    Returns:
        変換されたイベント辞書、またはトラック情報がない場合は None
    """
    track = item.get("track") or {}
    if not track:
        return None

    played_at_str = item.get("played_at", "")
    track_id = track.get("id", "")
    context = item.get("context")

    return {
        "play_id": _generate_play_id(played_at_str, track_id),
        "played_at_utc": played_at_str,
        "track_id": track_id,
        "track_name": track.get("name", "Unknown"),
        "artist_ids": _extract_artist_ids(track),
        "artist_names": _extract_artist_names(track),
        "album_id": _get_album_field(track, "id"),
        "album_name": _get_album_field(track, "name"),
        "ms_played": track.get("duration_ms"),
        "context_type": context.get("type") if context else None,
        "popularity": track.get("popularity"),
        "explicit": track.get("explicit"),
    }


def transform_plays_to_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spotifyの最近の再生履歴(Raw)を分析用イベント形式に変換する。

    Args:
        items: Spotify API (recently_played) の items リスト

    Returns:
        フラット化されたイベントデータのリスト
    """
    events = []
    for item in items:
        event = transform_play_item(item)
        if event:
            events.append(event)
    return events


def transform_track_info(track: dict[str, Any]) -> dict[str, Any]:
    """Spotifyのトラック情報をマスター保存用に変換する。"""
    return {
        "track_id": track.get("id"),
        "name": track.get("name"),
        "artist_ids": _extract_artist_ids(track),
        "artist_names": _extract_artist_names(track),
        "album_id": _get_album_field(track, "id"),
        "album_name": _get_album_field(track, "name"),
        "duration_ms": track.get("duration_ms"),
        "popularity": track.get("popularity"),
        "explicit": track.get("explicit"),
        "preview_url": track.get("preview_url"),
        "updated_at": datetime.now(timezone.utc),
    }


def transform_artist_info(artist: dict[str, Any]) -> dict[str, Any]:
    """Spotifyのアーティスト情報をマスター保存用に変換する。"""
    followers = artist.get("followers") or {}
    return {
        "artist_id": artist.get("id"),
        "name": artist.get("name"),
        "genres": artist.get("genres", []),
        "popularity": artist.get("popularity"),
        "followers_total": followers.get("total"),
        "updated_at": datetime.now(timezone.utc),
    }
