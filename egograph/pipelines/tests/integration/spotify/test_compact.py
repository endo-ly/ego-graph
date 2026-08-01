"""Spotify compaction のインテグレーションテスト。

MemoryS3 上で ingest 済みのデータに対する compaction (重複排除) を検証する。
"""

import io
from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import responses
from pydantic import SecretStr

from pipelines.sources.common.config import (
    Config,
    DuckDBConfig,
    R2Config,
    SpotifyConfig,
)
from pipelines.sources.spotify.pipeline import (
    run_spotify_compact,
    run_spotify_ingest,
)
from pipelines.sources.spotify.storage import SpotifyStorage
from pipelines.tests.e2e.test_browser_history_ingest import (
    _MemoryS3Server,
)


def _build_config(memory_s3) -> Config:
    """Spotify pipeline 用の設定を構築する。"""
    r2 = R2Config(
        endpoint_url=memory_s3.endpoint_url,
        access_key_id="test-access-key",
        secret_access_key=SecretStr("test-secret-key"),
        bucket_name="test-bucket",
    )
    return Config(
        spotify=SpotifyConfig(
            client_id="test-client-id",
            client_secret=SecretStr("test-client-secret"),
            refresh_token=SecretStr("test-refresh-token"),
        ),
        duckdb=DuckDBConfig(r2=r2),
    )


def _mock_spotify_api():
    """Spotify API の必要エンドポイントをモックする。"""
    responses.add(
        responses.POST,
        "https://accounts.spotify.com/api/token",
        json={
            "access_token": "mock-access-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.spotify.com/v1/me/player/recently-played",
        json={"items": []},
        status=200,
    )


def _seed_duplicate_events(memory_s3) -> None:
    """同一 play_id のイベントを2つのParquetファイルとして保存する。"""
    storage = SpotifyStorage(
        endpoint_url=memory_s3.endpoint_url,
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        bucket_name="test-bucket",
    )

    # 同一データを2回保存 (重複状態を意図的に作る)
    rows = [
        {
            "play_id": "dup-001",
            "track_id": "track-001",
            "played_at_utc": datetime(2026, 4, 1, 2, 30, tzinfo=UTC),
            "context_type": "playlist",
            "context_uri": "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
            "track_name": "Song A",
        },
        {
            "play_id": "dup-002",
            "track_id": "track-002",
            "played_at_utc": datetime(2026, 4, 1, 2, 26, tzinfo=UTC),
            "context_type": "album",
            "context_uri": "spotify:album:4yP0hdKOZPNshxUOjY0cZj",
            "track_name": "Song B",
        },
    ]
    table = pa.Table.from_pandas(pd.DataFrame(rows))

    # 2つの異なるファイルに同じデータを書き込む

    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)

    storage.s3.put_object(
        Bucket="test-bucket",
        Key="events/spotify/plays/year=2026/month=04/file-a.parquet",
        Body=buf.read(),
    )
    buf.seek(0)
    storage.s3.put_object(
        Bucket="test-bucket",
        Key="events/spotify/plays/year=2026/month=04/file-b.parquet",
        Body=buf.read(),
    )


def test_compact_deduplicates_events():
    """Compaction が同一 play_id のレコードを重複排除する。"""
    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)

        # 重複データを投入
        _seed_duplicate_events(memory_s3)

        # Compaction 実行 (投入月を明示。日付ドリフト回避)
        result = run_spotify_compact(config=config, year=2026, month=4)

        assert result["operation"] == "compact"
        assert len(result["compacted_keys"]) > 0

        # compacted ファイルを読み込んで行数を検証
        compacted_key = result["compacted_keys"][0]
        storage = SpotifyStorage(
            endpoint_url=memory_s3.endpoint_url,
            access_key_id="test-access-key",
            secret_access_key="test-secret-key",
            bucket_name="test-bucket",
        )
        resp = storage.s3.get_object(Bucket="test-bucket", Key=compacted_key)
        compacted_table = pq.read_table(io.BytesIO(resp["Body"].read()))
        # 4行(2ファイル×2行) → 2行に重複排除される
        assert len(compacted_table) == 2, (
            f"Expected 2 deduplicated rows, got {len(compacted_table)}"
        )


def test_compact_skips_empty_month():
    """データがない月の compaction はスキップされる。"""
    with _MemoryS3Server() as memory_s3:
        config = _build_config(memory_s3)
        _mock_spotify_api()

        # ingest 実行 (データなし → 何も保存されない)
        with patch(
            "pipelines.sources.spotify.ingest_pipeline.enrich_master_data",
        ):
            run_spotify_ingest(config=config)

        # Compaction 実行
        result = run_spotify_compact(config=config)

        assert len(result["compacted_keys"]) == 0
        assert len(result["skipped_targets"]) > 0
