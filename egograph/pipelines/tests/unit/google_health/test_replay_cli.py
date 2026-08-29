"""Google Health Raw replay CLIのテスト。"""

import json
import sys
from types import SimpleNamespace

from pipelines.main import main
from pipelines.sources.common.config import R2Config
from pydantic import SecretStr


def test_raw_replay_cli_provides_official_reset_command(monkeypatch, capsys):
    """Raw replay CLIがR2設定とreset指定を関数へ渡す。"""
    # Arrange
    r2_config = R2Config(
        endpoint_url="https://r2.example.test",
        access_key_id="key",
        secret_access_key=SecretStr("secret"),
    )
    captured: dict[str, object] = {}

    class FakeWriter:
        def __init__(self, **kwargs):
            captured["writer_kwargs"] = kwargs

    def fake_replay(writer, *, reset_compacted):
        captured["writer"] = writer
        captured["reset_compacted"] = reset_compacted
        return {"status": "succeeded"}

    monkeypatch.setattr(
        "pipelines.main.PipelinesConfig",
        lambda: SimpleNamespace(timezone="Asia/Tokyo"),
    )
    monkeypatch.setattr("pipelines.main._load_r2_config", lambda: r2_config)
    monkeypatch.setattr("pipelines.main.GoogleHealthWriter", FakeWriter)
    monkeypatch.setattr("pipelines.main.replay_google_health_raw", fake_replay)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pipelines",
            "google-health",
            "raw-replay",
            "--reset-compacted",
            "--json",
        ],
    )

    # Act
    main()

    # Assert
    assert captured["reset_compacted"] is True
    assert captured["writer_kwargs"]["timezone"].key == "Asia/Tokyo"
    assert json.loads(capsys.readouterr().out) == {"status": "succeeded"}
