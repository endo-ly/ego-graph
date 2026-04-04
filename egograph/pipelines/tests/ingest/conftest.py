"""ingest テスト用の共有 pytest フィクスチャ。"""

import pytest

from pipelines.sources.spotify.schema import SpotifySchema


@pytest.fixture
def temp_db(tmp_path):
    """テスト用の一時 DuckDB インスタンスを作成する。

    Args:
        tmp_path: Pytest 一時ディレクトリフィクスチャ

    Yields:
        DuckDB コネクション
    """
    db_path = tmp_path / "test.duckdb"
    conn = SpotifySchema.initialize_db(str(db_path))
    yield conn
    conn.close()
