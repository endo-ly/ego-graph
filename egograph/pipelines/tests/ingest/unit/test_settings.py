import os
from unittest.mock import patch

from pipelines.sources.common.settings import (
    GitHubWorklogSettings,
    PipelinesSettings,
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
