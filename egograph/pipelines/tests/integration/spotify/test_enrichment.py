"""Spotify マスターデータ補完 (enrichment) のインテグレーションテスト。

既存マスターIDとの比較 → 新規IDのみAPI取得 → S3保存 のフローを検証する。
"""

from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

from dataset_catalog import datasets
from pydantic import SecretStr

from pipelines.sources.spotify import ingest_pipeline as spotify_pipeline


def test_enrichment_fetches_only_new_master_data():
    """再生履歴から新規IDのみがマスター取得される。"""
    # Arrange: 既存のトラック/アーティストIDと新規データ
    items = [
        {
            "played_at": "2026-04-01T00:00:00Z",
            "track": {
                "id": "t1",
                "name": "Song A",
                "artists": [{"id": "a1", "name": "Artist A"}],
                "album": {"id": "alb1", "name": "Album A"},
                "duration_ms": 1000,
                "popularity": 10,
                "explicit": False,
            },
        },
        {
            "played_at": "2026-04-02T00:00:00Z",
            "track": {
                "id": "t2",
                "name": "Song B",
                "artists": [{"id": "a2", "name": "Artist B"}],
                "album": {"id": "alb2", "name": "Album B"},
                "duration_ms": 2000,
                "popularity": 20,
                "explicit": True,
            },
        },
    ]

    mock_collector = MagicMock()
    mock_collector.get_tracks.return_value = [
        {"id": "t2", "name": "Song B", "artists": [{"id": "a2", "name": "Artist B"}]}
    ]
    mock_collector.get_artists.return_value = [
        {"id": "a2", "name": "Artist B", "genres": ["j-pop"]}
    ]

    mock_storage = MagicMock()

    r2_conf = SimpleNamespace(
        endpoint_url="https://example.invalid",
        access_key_id="test_access_key",
        secret_access_key=SecretStr("test_secret"),
        bucket_name="test-bucket",
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
    )

    # Act: t1/a1 は既存、t2/a2 は新規
    spotify_pipeline.enrich_master_data(
        items,
        collector=mock_collector,
        storage=mock_storage,
        r2_conf=r2_conf,
        existing_track_ids={"t1"},
        existing_artist_ids={"a1"},
    )

    # Assert: 新規IDのみ取得される
    mock_collector.get_tracks.assert_called_once_with(["t2"])
    mock_collector.get_artists.assert_called_once_with(["a2"])

    # 生レスポンスの保存が行われる
    mock_storage.save_raw_json.assert_any_call(ANY, prefix="spotify/tracks")
    mock_storage.save_raw_json.assert_any_call(ANY, prefix="spotify/artists")

    # マスター保存が行われる
    mock_storage.save_master_parquet.assert_any_call(
        ANY, datasets.SPOTIFY_TRACKS, year=ANY, month=ANY
    )
    mock_storage.save_master_parquet.assert_any_call(
        ANY, datasets.SPOTIFY_ARTISTS, year=ANY, month=ANY
    )


def test_enrichment_skips_when_all_existing():
    """全IDが既存の場合、API通信も保存も行わない。"""
    items = [
        {
            "played_at": "2026-04-01T00:00:00Z",
            "track": {
                "id": "t1",
                "name": "Song A",
                "artists": [{"id": "a1", "name": "Artist A"}],
                "album": {"id": "alb1", "name": "Album A"},
                "duration_ms": 1000,
                "popularity": 10,
                "explicit": False,
            },
        },
    ]

    mock_collector = MagicMock()
    mock_storage = MagicMock()

    r2_conf = SimpleNamespace(
        endpoint_url="https://example.invalid",
        access_key_id="test_access_key",
        secret_access_key=SecretStr("test_secret"),
        bucket_name="test-bucket",
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
    )

    # Act: 全IDが既存
    spotify_pipeline.enrich_master_data(
        items,
        collector=mock_collector,
        storage=mock_storage,
        r2_conf=r2_conf,
        existing_track_ids={"t1"},
        existing_artist_ids={"a1"},
    )

    # Assert: API通信も保存も行わない
    mock_collector.get_tracks.assert_not_called()
    mock_collector.get_artists.assert_not_called()
    mock_storage.save_raw_json.assert_not_called()
    mock_storage.save_master_parquet.assert_not_called()
