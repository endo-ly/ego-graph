"""DuckDB ライターのテスト。"""

from pipelines.sources.spotify.writer import SpotifyDuckDBWriter
from pipelines.tests.ingest.fixtures.spotify_responses import get_mock_recently_played


def test_upsert_plays(temp_db):
    """再生履歴の挿入をテストする。"""
    # Arrange: ライターの初期化とテストデータの準備
    writer = SpotifyDuckDBWriter(temp_db)
    mock_data = get_mock_recently_played(2)

    # Act: 再生履歴のアップサートを実行
    count = writer.upsert_plays(mock_data["items"])

    # Assert: 挿入された件数を検証
    assert count == 2
    result = temp_db.execute("SELECT COUNT(*) FROM raw.spotify_plays").fetchone()
    assert result[0] == 2

    # Act 2: 同じデータを再度アップサート（べき等性の確認）
    count2 = writer.upsert_plays(mock_data["items"])
    assert count2 == 2

    # Assert 2: 重複して挿入されていないことを検証
    result = temp_db.execute("SELECT COUNT(*) FROM raw.spotify_plays").fetchone()
    assert result[0] == 2  # 依然として2（4ではない）


def test_upsert_plays_empty(temp_db):
    """空の入力の処理をテストする。"""
    # Arrange: ライターの初期化
    writer = SpotifyDuckDBWriter(temp_db)

    # Act: 空のリストでアップサートを実行
    count = writer.upsert_plays([])

    # Assert: 挿入件数が 0 であることを検証
    assert count == 0


def test_upsert_tracks(temp_db):
    """楽曲マスタデータの挿入をテストする。"""
    # Arrange: ライターの初期化とデータの準備
    writer = SpotifyDuckDBWriter(temp_db)
    mock_data = get_mock_recently_played(2)

    # Act: 楽曲情報のアップサートを実行
    count = writer.upsert_tracks(mock_data["items"])

    # Assert: 正しく挿入されていることを検証
    assert count == 2
    result = temp_db.execute("SELECT COUNT(*) FROM mart.spotify_tracks").fetchone()
    assert result[0] == 2


def test_upsert_tracks_deduplication(temp_db):
    """同じ楽曲が複数回現れた際の重複除去をテストする。"""
    # Arrange: ライターの初期化と重複データの準備
    writer = SpotifyDuckDBWriter(temp_db)
    mock_data = get_mock_recently_played(2)
    duplicate_items = [mock_data["items"][0], mock_data["items"][0]]

    # Act: 重複データでアップサートを実行
    count = writer.upsert_tracks(duplicate_items)

    # Assert: 1曲のみ挿入されていることを検証
    assert count == 1
    result = temp_db.execute("SELECT COUNT(*) FROM mart.spotify_tracks").fetchone()
    assert result[0] == 1


def test_get_stats(temp_db):
    """統計情報の取得をテストする。"""
    # Arrange: テストデータの準備と挿入
    writer = SpotifyDuckDBWriter(temp_db)
    mock_data = get_mock_recently_played(2)
    writer.upsert_plays(mock_data["items"])
    writer.upsert_tracks(mock_data["items"])

    # Act: 統計情報を取得
    stats = writer.get_stats()

    # Assert: 統計内容を検証
    assert stats["total_plays"] == 2
    assert stats["total_tracks"] == 2
    assert stats["latest_play"] is not None


def test_play_id_generation(temp_db):
    """play_id が正しく生成されることをテストする。"""
    # Arrange: テストデータの挿入
    writer = SpotifyDuckDBWriter(temp_db)
    mock_data = get_mock_recently_played(1)
    writer.upsert_plays(mock_data["items"])

    # Act: 保存された play_id を取得
    result = temp_db.execute("SELECT play_id FROM raw.spotify_plays").fetchone()
    play_id = result[0]

    # Assert: play_id に期待される情報
    # （タイムスタンプと track_id）が含まれていることを検証
    assert "2025-12-14T02:30:00.000Z" in play_id
    assert "3n3Ppam7vgaVa1iaRUc9Lp" in play_id
