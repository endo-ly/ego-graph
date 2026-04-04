"""Spotify コレクタのテスト。"""

import re

import responses

from pipelines.sources.common.utils import iso8601_to_unix_ms
from pipelines.sources.spotify.collector import SpotifyCollector
from pipelines.tests.ingest.fixtures.spotify_responses import (
    INCREMENTAL_TEST_TIMESTAMPS,
    get_mock_recently_played,
    get_mock_recently_played_with_timestamps,
)


@responses.activate
def test_get_recently_played_success():
    """最近再生したトラックの取得成功をテストする。"""
    # Arrange: トークンリフレッシュと API エンドポイントをモック
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json=get_mock_recently_played(2),
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Act: 最近再生したトラックを取得
    result = collector.get_recently_played(limit=2)

    # Assert: 取得結果を検証
    assert len(result) == 2
    assert result[0]["track"]["name"] == "Mr. Brightside"
    assert result[1]["track"]["name"] == "Blinding Lights"


@responses.activate
def test_get_recently_played_empty():
    """空のレスポンスの処理をテストする。"""
    # Arrange: 空のレスポンスを返すようにモック
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json={"items": []},
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Act: 最近再生したトラックを取得
    result = collector.get_recently_played()

    # Assert: 結果が空であることを検証
    assert len(result) == 0


@responses.activate
def test_get_recently_played_with_after_parameter():
    """afterパラメータを使用した増分取得をテストする。"""
    # Arrange: 増分取得用のテスト時刻とモックデータを準備

    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )

    # afterより新しいトラックのみ返すように設定
    newer_tracks = get_mock_recently_played_with_timestamps(
        [INCREMENTAL_TEST_TIMESTAMPS["newer"], INCREMENTAL_TEST_TIMESTAMPS["newest"]]
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json=newer_tracks,
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Act: after パラメータを指定して取得
    after_ms = iso8601_to_unix_ms(INCREMENTAL_TEST_TIMESTAMPS["recent"])
    result = collector.get_recently_played(after=after_ms)

    # Assert: newer および newest のトラックが取得されていることを検証
    assert len(result) == 2
    assert result[0]["played_at"] == INCREMENTAL_TEST_TIMESTAMPS["newer"]
    assert result[1]["played_at"] == INCREMENTAL_TEST_TIMESTAMPS["newest"]


@responses.activate
def test_get_recently_played_incremental_no_new_data():
    """増分取得で新しいデータがない場合をテストする。"""
    # Arrange: 新しいデータがない状態をモック

    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json={"items": []},
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Act: 取得を実行
    after_ms = iso8601_to_unix_ms("2025-12-14T03:00:00.000Z")
    result = collector.get_recently_played(after=after_ms)

    # Assert: 結果が空であることを検証
    assert len(result) == 0


@responses.activate
def test_get_recently_played_backward_compatible():
    """afterパラメータなしの従来の動作が保たれることをテストする。"""
    # Arrange: モックデータを準備
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json=get_mock_recently_played(2),
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Act: after なしで取得を実行
    result = collector.get_recently_played()

    # Assert: 正しくデータが取得されていることを検証
    assert len(result) == 2
    assert result[0]["track"]["name"] == "Mr. Brightside"


@responses.activate
def test_get_audio_features_success():
    """Audio Featuresの取得成功をテストする。"""
    # Arrange: Audio Features エンドポイントをモック
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )

    mock_features = {
        "audio_features": [
            {"id": "track1", "danceability": 0.5, "energy": 0.8, "valence": 0.3},
            {"id": "track2", "danceability": 0.7, "energy": 0.4, "valence": 0.9},
        ]
    }
    responses.add(
        responses.GET,
        re.compile(r"https://api.spotify.com/v1/audio-features.*"),
        json=mock_features,
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    # Act: 指定したトラックの Audio Features を取得
    result = collector.get_audio_features(track_ids=["track1", "track2"])

    # Assert: 特徴量が正しく取得できていることを検証
    assert len(result) == 2
    assert result[0]["id"] == "track1"
    assert result[0]["danceability"] == 0.5
    assert result[1]["id"] == "track2"
    assert result[1]["valence"] == 0.9


@responses.activate
def test_get_tracks_success():
    """トラック情報の取得成功をテストする。"""
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    responses.add(
        responses.GET,
        re.compile(r"https://api.spotify.com/v1/tracks.*"),
        json={
            "tracks": [
                {"id": "track1", "name": "Song A"},
                {"id": "track2", "name": "Song B"},
            ]
        },
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    result = collector.get_tracks(track_ids=["track1", "track2"])

    assert len(result) == 2
    assert result[0]["id"] == "track1"
    assert result[1]["name"] == "Song B"


@responses.activate
def test_get_artists_success():
    """アーティスト情報の取得成功をテストする。"""
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    responses.add(
        responses.GET,
        re.compile(r"https://api.spotify.com/v1/artists.*"),
        json={
            "artists": [
                {"id": "artist1", "name": "Artist A"},
                {"id": "artist2", "name": "Artist B"},
            ]
        },
        status=200,
    )

    collector = SpotifyCollector(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )

    result = collector.get_artists(artist_ids=["artist1", "artist2"])

    assert len(result) == 2
    assert result[0]["id"] == "artist1"
    assert result[1]["name"] == "Artist B"
