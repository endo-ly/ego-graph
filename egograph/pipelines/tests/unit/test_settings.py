import os
from unittest.mock import patch

from egograph_paths import ANALYTICS_DUCKDB_PATH, PARQUET_DATA_DIR
from pipelines.sources.common.settings import (
    GitHubWorklogSettings,
    PipelinesSettings,
    R2Settings,
    YouTubeSettings,
)


def test_ingest_settings_google_activity_unset_is_none():
    with patch.dict(os.environ, {}, clear=True):
        config = PipelinesSettings.load()

    assert config.google_activity is None


def test_ingest_settings_google_activity_set_loads_config():
    env = {
        "GOOGLE_ACTIVITY_ACCOUNTS": '["account1"]',
    }
    with patch.dict(os.environ, env, clear=True):
        config = PipelinesSettings.load()

    assert config.google_activity is not None
    assert config.google_activity.accounts == ["account1"]


def test_github_worklog_settings_accepts_github_pat():
    env = {
        "GITHUB_PAT": "pat-token",
        "GITHUB_LOGIN": "test-user",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = GitHubWorklogSettings()

    assert settings.token.get_secret_value() == "pat-token"


def test_github_worklog_settings_accepts_github_token_fallback():
    env = {
        "GITHUB_TOKEN": "legacy-token",
        "GITHUB_LOGIN": "test-user",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = GitHubWorklogSettings()

    assert settings.token.get_secret_value() == "legacy-token"


def test_r2_settings_defaults_local_parquet_root_from_shared_paths():
    env = {
        "R2_ENDPOINT_URL": "https://test.r2.cloudflarestorage.com",
        "R2_ACCESS_KEY_ID": "test-key",
        "R2_SECRET_ACCESS_KEY": "test-secret",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = R2Settings()

    assert settings.local_parquet_root == str(PARQUET_DATA_DIR)


def test_pipelines_settings_defaults_duckdb_path_from_shared_paths():
    with patch.dict(os.environ, {}, clear=True):
        config = PipelinesSettings.load()

    assert config.duckdb is not None
    assert config.duckdb.db_path == str(ANALYTICS_DUCKDB_PATH)


def test_settings_load_youtube_api_key_for_browser_history_pipeline():
    """YOUTUBE_API_KEY が共通設定から読み込める。"""
    env = {
        "YOUTUBE_API_KEY": "test-api-key-123",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = YouTubeSettings()

    assert settings.youtube_api_key.get_secret_value() == "test-api-key-123"
    config = settings.to_config()
    assert config.youtube_api_key.get_secret_value() == "test-api-key-123"
