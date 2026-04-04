"""Spotify API レスポンス用のテストフィクスチャ。"""

from typing import Any, Dict, List

MOCK_RECENTLY_PLAYED_RESPONSE = {
    "items": [
        {
            "track": {
                "id": "3n3Ppam7vgaVa1iaRUc9Lp",
                "name": "Mr. Brightside",
                "artists": [{"id": "0C0XlULifJtAgn6ZNCW2eu", "name": "The Killers"}],
                "album": {"id": "4OHNH3sDzIxnmUADXzv2kT", "name": "Hot Fuss"},
                "duration_ms": 222973,
                "popularity": 85,
            },
            "played_at": "2025-12-14T02:30:00.000Z",
            "context": {
                "type": "playlist",
                "uri": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
            },
        },
        {
            "track": {
                "id": "0VjIjW4GlUZAMYd2vXMi3b",
                "name": "Blinding Lights",
                "artists": [{"id": "1Xyo4u8uXC1ZmMpatF05PJ", "name": "The Weeknd"}],
                "album": {"id": "4yP0hdKOZPNshxUOjY0cZj", "name": "After Hours"},
                "duration_ms": 200040,
                "popularity": 92,
            },
            "played_at": "2025-12-14T02:26:00.000Z",
            "context": {"type": "album", "uri": "spotify:album:4yP0hdKOZPNshxUOjY0cZj"},
        },
    ]
}


def get_mock_recently_played(count: int = 2):
    """モックの最近再生したトラックのレスポンスを取得する。

    Args:
        count: 返す項目数

    Returns:
        モックデータを含む "items" キーを持つ辞書
    """
    return {"items": MOCK_RECENTLY_PLAYED_RESPONSE["items"][:count]}


def get_mock_recently_played_with_timestamps(
    timestamps: List[str], base_track_index: int = 0
) -> Dict[str, Any]:
    """指定したタイムスタンプでモックレスポンスを生成する。

    Args:
        timestamps: ISO 8601形式のタイムスタンプリスト
        base_track_index: 使用する楽曲のベースインデックス（デフォルト: 0）

    Returns:
        指定したタイムスタンプを持つモックレスポンス
    """
    items = []
    available_tracks = MOCK_RECENTLY_PLAYED_RESPONSE["items"]

    for i, timestamp in enumerate(timestamps):
        track_index = (base_track_index + i) % len(available_tracks)
        base_item = available_tracks[track_index]

        item = {
            "track": base_item["track"].copy(),
            "played_at": timestamp,
            "context": base_item.get("context", {}).copy()
            if base_item.get("context")
            else None,
        }
        items.append(item)

    return {"items": items}


# 増分取得テスト用の定義済みタイムスタンプセット
INCREMENTAL_TEST_TIMESTAMPS = {
    "old": "2025-12-14T01:00:00.000Z",
    "recent": "2025-12-14T02:30:00.000Z",
    "newer": "2025-12-14T02:45:00.000Z",
    "newest": "2025-12-14T03:00:00.000Z",
}
