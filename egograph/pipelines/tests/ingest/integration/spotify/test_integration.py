"""Spotify パイプラインのインテグレーションテスト。"""

from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
import responses
from pydantic import SecretStr

from pipelines.sources.common.utils import iso8601_to_unix_ms
from pipelines.sources.spotify import ingest_pipeline as spotify_pipeline
from pipelines.sources.spotify.collector import SpotifyCollector
from pipelines.sources.spotify.schema import SpotifySchema
from pipelines.sources.spotify.writer import SpotifyDuckDBWriter
from pipelines.tests.ingest.fixtures.spotify_responses import (
    INCREMENTAL_TEST_TIMESTAMPS,
    get_mock_recently_played,
    get_mock_recently_played_with_timestamps,
)


@pytest.mark.integration
@responses.activate
def test_full_pipeline(tmp_path):
    """収集から保存までの完全なパイプラインをテストする。"""
    # Arrange: DB パスとモックの設定
    db_path = tmp_path / "analytics.duckdb"

    # Spotify 認証をモック
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )

    # Spotify API をモック
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json=get_mock_recently_played(2),
        status=200,
    )

    # Act 1: データ収集
    collector = SpotifyCollector(
        client_id="test_id", client_secret="test_secret", refresh_token="test_token"
    )
    recently_played = collector.get_recently_played()

    # Assert 1: 収集件数を検証
    assert len(recently_played) == 2

    # Act 2: DB 初期化と書き込み
    conn = SpotifySchema.initialize_db(str(db_path))
    SpotifySchema.create_indexes(conn)
    writer = SpotifyDuckDBWriter(conn)
    plays_count = writer.upsert_plays(recently_played)
    tracks_count = writer.upsert_tracks(recently_played)

    # Assert 2: 書き込み件数と統計情報、データ整合性を検証
    assert plays_count == 2
    assert tracks_count == 2

    stats = writer.get_stats()
    assert stats["total_plays"] == 2
    assert stats["total_tracks"] == 2
    assert stats["latest_play"] is not None

    # 再生履歴テーブルの検証
    plays_result = conn.execute("""
        SELECT track_name, artist_names
        FROM raw.spotify_plays
        ORDER BY played_at_utc DESC
    """).fetchall()
    assert len(plays_result) == 2
    assert plays_result[0][0] == "Mr. Brightside"
    assert "The Killers" in plays_result[0][1]

    # 楽曲マスタテーブルの検証
    tracks_result = conn.execute("""
        SELECT name, duration_ms, popularity
        FROM mart.spotify_tracks
        ORDER BY popularity DESC
    """).fetchall()
    assert len(tracks_result) == 2
    assert tracks_result[0][0] == "Blinding Lights"
    assert tracks_result[0][2] == 92

    conn.close()


@pytest.mark.integration
def test_idempotent_pipeline(tmp_path):
    """パイプラインがべき等であることをテストする - 2回実行してもデータが重複しない。"""
    # Arrange: DB とテストデータの準備
    db_path = tmp_path / "analytics.duckdb"
    mock_data = get_mock_recently_played(2)

    # Act 1: 1回目の書き込み実行
    conn = SpotifySchema.initialize_db(str(db_path))
    writer = SpotifyDuckDBWriter(conn)
    writer.upsert_plays(mock_data["items"])
    writer.upsert_tracks(mock_data["items"])
    stats_1 = writer.get_stats()
    conn.close()

    # Act 2: 2回目の書き込み実行（全く同じデータ）
    conn = SpotifySchema.initialize_db(str(db_path))
    writer = SpotifyDuckDBWriter(conn)
    writer.upsert_plays(mock_data["items"])
    writer.upsert_tracks(mock_data["items"])
    stats_2 = writer.get_stats()
    conn.close()

    # Assert: 2回実行しても件数が増えていないことを検証
    assert stats_1["total_plays"] == stats_2["total_plays"]
    assert stats_1["total_tracks"] == stats_2["total_tracks"]
    assert stats_1["total_plays"] == 2
    assert stats_1["total_tracks"] == 2


@pytest.mark.integration
@responses.activate
def test_incremental_pipeline_run(tmp_path):
    """増分取得モードでのパイプライン実行をテストする。"""
    # Arrange: DB と増分テスト用時刻の準備
    db_path = tmp_path / "analytics.duckdb"

    # --- 1回目の実行のセットアップ ---
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    initial_data = get_mock_recently_played_with_timestamps(
        [INCREMENTAL_TEST_TIMESTAMPS["old"], INCREMENTAL_TEST_TIMESTAMPS["recent"]]
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json=initial_data,
        status=200,
    )

    # Act 1: 1回目の収集と保存（初期データ）
    collector = SpotifyCollector(
        client_id="test_id", client_secret="test_secret", refresh_token="test_token"
    )
    recently_played_1 = collector.get_recently_played()
    conn = SpotifySchema.initialize_db(str(db_path))
    writer = SpotifyDuckDBWriter(conn)
    writer.upsert_plays(recently_played_1)
    writer.upsert_tracks(recently_played_1)

    # Assert 1: 初期状態の統計を検証
    stats_1 = writer.get_stats()
    assert stats_1["total_plays"] == 2
    latest_play_str = stats_1["latest_play"].isoformat()
    assert latest_play_str.startswith("2025-12-14T02:30:00")
    conn.close()

    # --- 2回目の実行（増分）のセットアップ ---
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={"access_token": "mock_token", "expires_in": 3600, "token_type": "Bearer"},
        status=200,
    )
    incremental_data = get_mock_recently_played_with_timestamps(
        [INCREMENTAL_TEST_TIMESTAMPS["newer"], INCREMENTAL_TEST_TIMESTAMPS["newest"]]
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json=incremental_data,
        status=200,
    )

    # Act 2: 直近の再生時刻を after として 2 回目の取得と保存を実行
    conn = SpotifySchema.initialize_db(str(db_path))
    writer = SpotifyDuckDBWriter(conn)
    stats_before = writer.get_stats()
    after_ms = iso8601_to_unix_ms(stats_before["latest_play"])

    collector_2 = SpotifyCollector(
        client_id="test_id", client_secret="test_secret", refresh_token="test_token"
    )
    recently_played_2 = collector_2.get_recently_played(after=after_ms)
    writer.upsert_plays(recently_played_2)
    writer.upsert_tracks(recently_played_2)

    # Assert 2: 増分データが正しく追加されていることを検証
    assert len(recently_played_2) == 2
    stats_2 = writer.get_stats()
    assert stats_2["total_plays"] == 4
    latest_play_str_2 = stats_2["latest_play"].isoformat()
    assert latest_play_str_2.startswith("2025-12-14T03:00:00")
    conn.close()


@pytest.mark.integration
def test_master_enrichment_flow():
    """再生履歴から新規IDのみマスター取得されることをテストする。"""
    # Arrange: 再生履歴とマスターのモックを準備
    items = [
        {
            "played_at": "2025-01-01T00:00:00Z",
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
            "played_at": "2025-01-02T00:00:00Z",
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

    # Act: マスター補完処理のみを実行
    spotify_pipeline.enrich_master_data(
        items,
        collector=mock_collector,
        storage=mock_storage,
        r2_conf=r2_conf,
        existing_track_ids={"t1"},
        existing_artist_ids={"a1"},
    )

    # Assert: 新規IDのみ取得されることを検証
    mock_collector.get_tracks.assert_called_once_with(["t2"])
    mock_collector.get_artists.assert_called_once_with(["a2"])

    # 生レスポンスの保存が行われることを確認
    mock_storage.save_raw_json.assert_any_call(ANY, prefix="spotify/tracks")
    mock_storage.save_raw_json.assert_any_call(ANY, prefix="spotify/artists")

    # マスター保存が行われることを確認
    mock_storage.save_master_parquet.assert_any_call(
        ANY, prefix="spotify/tracks", year=ANY, month=ANY
    )
    mock_storage.save_master_parquet.assert_any_call(
        ANY, prefix="spotify/artists", year=ANY, month=ANY
    )
