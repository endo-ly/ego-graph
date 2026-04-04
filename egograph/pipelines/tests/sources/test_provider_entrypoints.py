"""Spotify/GitHub source entrypoint tests."""

from pipelines.sources.common.config import Config, DuckDBConfig, R2Config
from pipelines.sources.github.pipeline import run_github_compact, run_github_ingest
from pipelines.sources.spotify.pipeline import run_spotify_compact, run_spotify_ingest
from pydantic import SecretStr


def _config() -> Config:
    return Config(
        duckdb=DuckDBConfig(
            r2=R2Config(
                endpoint_url="https://r2.example.com",
                access_key_id="access-key",
                secret_access_key=SecretStr("secret"),
                bucket_name="egograph",
            )
        )
    )


def test_run_spotify_ingest_delegates_to_existing_pipeline(monkeypatch):
    """Spotify ingest entrypoint は既存 pipeline 実装を呼ぶ。"""
    called = {}

    def fake_run_pipeline(config):
        called["config"] = config

    monkeypatch.setattr(
        "pipelines.sources.spotify.pipeline._run_ingest_pipeline",
        fake_run_pipeline,
    )

    result = run_spotify_ingest(_config())

    assert called["config"] == _config()
    assert result == {
        "provider": "spotify",
        "operation": "ingest",
        "status": "succeeded",
    }


def test_run_github_ingest_delegates_to_existing_pipeline(monkeypatch):
    """GitHub ingest entrypoint は既存 pipeline 実装を呼ぶ。"""
    called = {}

    def fake_run_pipeline(config):
        called["config"] = config

    monkeypatch.setattr(
        "pipelines.sources.github.pipeline._run_ingest_pipeline",
        fake_run_pipeline,
    )

    result = run_github_ingest(_config())

    assert called["config"] == _config()
    assert result == {
        "provider": "github",
        "operation": "ingest",
        "status": "succeeded",
    }


def test_run_spotify_compact_returns_compacted_and_skipped_targets(monkeypatch):
    """Spotify compaction 結果を summary dict に整形する。"""
    calls = []

    class FakeStorage:
        def __init__(self, **kwargs):
            pass

        def compact_month(self, **kwargs):
            calls.append(kwargs)
            if kwargs["dataset_path"] == "spotify/artists":
                return None
            return f"compacted/{kwargs['dataset_path']}/data.parquet"

    monkeypatch.setattr(
        "pipelines.sources.spotify.pipeline.SpotifyStorage",
        FakeStorage,
    )

    result = run_spotify_compact(_config(), year=2026, month=4)

    assert len(calls) == 3
    assert result == {
        "provider": "spotify",
        "operation": "compact",
        "target_months": ["2026-04"],
        "compacted_keys": [
            "compacted/spotify/plays/data.parquet",
            "compacted/spotify/tracks/data.parquet",
        ],
        "skipped_targets": ["spotify/artists:2026-04"],
    }


def test_run_github_compact_raises_after_collecting_failures(monkeypatch):
    """GitHub compaction は失敗 dataset をまとめて RuntimeError にする。"""

    class FakeStorage:
        def __init__(self, **kwargs):
            pass

        def compact_month(self, **kwargs):
            if kwargs["dataset_path"] == "github/pull_requests":
                raise RuntimeError("boom")
            return "compacted/events/github/commits/year=2026/month=04/data.parquet"

    monkeypatch.setattr(
        "pipelines.sources.github.pipeline.GitHubWorklogStorage",
        FakeStorage,
    )

    try:
        run_github_compact(_config(), year=2026, month=4)
    except RuntimeError as exc:
        assert str(exc) == "GitHub compaction failed for: github/pull_requests:2026-04"
    else:
        raise AssertionError("RuntimeError was not raised")
