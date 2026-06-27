"""Bootstrap compaction tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pipelines.sources.common.bootstrap_compact import (
    _compact_browser_history,
    _compact_github,
    _compact_spotify,
    _compact_youtube,
    main,
)
from pipelines.sources.common.config import Config, DuckDBConfig, R2Config
from pydantic import SecretStr


def _build_config() -> Config:
    return Config(
        duckdb=DuckDBConfig(
            r2=R2Config(
                endpoint_url="https://example.com",
                access_key_id="test-access-key",
                secret_access_key=SecretStr("test-secret-key"),
                bucket_name="egograph",
                raw_path="raw/",
                events_path="events/",
                master_path="master/",
            )
        )
    )


class TestCompactSpotify:
    """_compact_spotify tests."""

    def test_compacts_all_discovered_months_for_each_dataset(self, monkeypatch):
        s3_client = object()
        storage = Mock()

        discovered_months = {
            ("events/", "events", "spotify/plays"): [(2024, 1), (2024, 2)],
            ("master/", "master", "spotify/tracks"): [(2024, 1)],
            ("master/", "master", "spotify/artists"): [],
        }

        def mock_discover(s3, bucket_name, root_prefix, dataset):
            assert s3 is s3_client
            assert bucket_name == "egograph"
            return discovered_months[
                (root_prefix, dataset.domain.value, dataset.path)
            ]

        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._discover_dataset_months",
            mock_discover,
        )

        failures = _compact_spotify(
            s3_client=s3_client,
            bucket_name="egograph",
            events_path="events/",
            master_path="master/",
            storage=storage,
        )

        assert failures == []
        assert storage.compact_month.call_count == 3


class TestCompactGitHub:
    """_compact_github tests."""

    def test_collects_failures_and_continues(self, monkeypatch):
        s3_client = object()
        storage = Mock()
        storage.compact_month.side_effect = [None, RuntimeError("boom"), None]

        discovered_months = {
            ("events/", "events", "github/commits"): [(2024, 1), (2024, 2)],
            ("events/", "events", "github/pull_requests"): [(2024, 1)],
        }

        def mock_discover(s3, bucket_name, root_prefix, dataset):
            assert s3 is s3_client
            assert bucket_name == "egograph"
            return discovered_months[
                (root_prefix, dataset.domain.value, dataset.path)
            ]

        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._discover_dataset_months",
            mock_discover,
        )

        failures = _compact_github(
            s3_client=s3_client,
            bucket_name="egograph",
            events_path="events/",
            storage=storage,
        )

        assert failures == ["github:github/commits:2024-02"]
        assert storage.compact_month.call_count == 3


class TestCompactBrowserHistory:
    """_compact_browser_history tests."""

    def test_collects_failures_and_continues(self, monkeypatch):
        s3_client = object()
        storage = Mock()
        storage.compact_month.side_effect = [None, RuntimeError("boom")]

        discovered_months = {
            ("events/", "events", "browser_history/page_views"): [(2024, 1), (2024, 2)],
        }

        def mock_discover(s3, bucket_name, root_prefix, dataset):
            assert s3 is s3_client
            assert bucket_name == "egograph"
            return discovered_months[
                (root_prefix, dataset.domain.value, dataset.path)
            ]

        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._discover_dataset_months",
            mock_discover,
        )

        failures = _compact_browser_history(
            s3_client=s3_client,
            bucket_name="egograph",
            events_path="events/",
            storage=storage,
        )

        assert failures == ["browser_history:browser_history/page_views:2024-02"]
        assert storage.compact_month.call_count == 2


class TestCompactYouTube:
    """_compact_youtube tests."""

    def test_compacts_all_discovered_months(self, monkeypatch):
        s3_client = object()
        storage = Mock()

        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._discover_dataset_months",
            lambda s3, bucket_name, root_prefix, dataset: [(2025, 1), (2025, 2)],
        )

        failures = _compact_youtube(
            s3_client=s3_client,
            bucket_name="egograph",
            events_path="events/",
            storage=storage,
        )

        assert failures == []
        assert storage.compact_month.call_count == 2
        storage.compact_month.assert_any_call(year=2025, month=1)
        storage.compact_month.assert_any_call(year=2025, month=2)

    def test_collects_failures_and_continues(self, monkeypatch):
        s3_client = object()
        storage = Mock()
        storage.compact_month.side_effect = [None, RuntimeError("boom")]

        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._discover_dataset_months",
            lambda s3, bucket_name, root_prefix, dataset: [(2025, 1), (2025, 2)],
        )

        failures = _compact_youtube(
            s3_client=s3_client,
            bucket_name="egograph",
            events_path="events/",
            storage=storage,
        )

        assert failures == ["youtube:youtube/watch_events:2025-02"]
        assert storage.compact_month.call_count == 2


class TestMain:
    """main tests."""

    def test_runs_selected_provider_only(self, monkeypatch):
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._parse_args",
            lambda: SimpleNamespace(provider="spotify"),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.PipelinesSettings.load",
            _build_config,
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._build_s3_client",
            lambda **_: object(),
        )
        spotify_compact = Mock(return_value=[])
        github_compact = Mock(return_value=[])
        browser_history_compact = Mock(return_value=[])
        youtube_compact = Mock(return_value=[])
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_spotify",
            spotify_compact,
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_github",
            github_compact,
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_browser_history",
            browser_history_compact,
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_youtube",
            youtube_compact,
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.SpotifyStorage",
            Mock(),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.GitHubWorklogStorage",
            Mock(),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.BrowserHistoryStorage",
            Mock(),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.YouTubeStorage",
            Mock(),
        )

        main()

        spotify_compact.assert_called_once()
        github_compact.assert_not_called()
        browser_history_compact.assert_not_called()
        youtube_compact.assert_not_called()

    def test_raises_when_any_provider_fails(self, monkeypatch):
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._parse_args",
            lambda: SimpleNamespace(provider="all"),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.PipelinesSettings.load",
            _build_config,
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._build_s3_client",
            lambda **_: object(),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_spotify",
            Mock(return_value=["spotify:spotify/plays:2024-01"]),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_github",
            Mock(return_value=[]),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_browser_history",
            Mock(return_value=[]),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact._compact_youtube",
            Mock(return_value=[]),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.SpotifyStorage",
            Mock(),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.GitHubWorklogStorage",
            Mock(),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.BrowserHistoryStorage",
            Mock(),
        )
        monkeypatch.setattr(
            "pipelines.sources.common.bootstrap_compact.YouTubeStorage",
            Mock(),
        )

        with pytest.raises(RuntimeError, match="spotify:spotify/plays:2024-01"):
            main()
