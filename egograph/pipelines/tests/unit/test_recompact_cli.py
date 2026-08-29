"""Recompact CLIのテスト。"""

import json
import sys
from types import SimpleNamespace

import pytest
from pipelines.main import _build_parser, main
from pipelines.sources.common.config import R2Config
from pydantic import SecretStr


@pytest.mark.parametrize(
    "arguments",
    [
        ["recompact", "--provider", "google_health"],
        ["recompact", "--dataset", "google_health.samples"],
        ["recompact", "--provider", "google_health", "--year", "2026", "--month", "8"],
    ],
)
def test_recompact_cli_accepts_google_health_selectors(arguments):
    """recompact CLIがGoogle Healthのprovider・dataset・月指定を受け付ける。"""
    # Arrange
    parser = _build_parser()

    # Act
    parsed = parser.parse_args(arguments)

    # Assert
    assert parsed.command == "recompact"


def test_removed_google_health_replay_cli_is_rejected():
    """旧Google Health専用CLIを公開入口として受け付けない。"""
    # Arrange
    parser = _build_parser()

    # Act / Assert
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["google-health", "raw-replay"])
    assert exc_info.value.code == 2


def test_reset_compacted_is_not_a_public_recompact_option():
    """compactedのreset方式を公開CLIの選択肢にしない。"""
    # Arrange
    parser = _build_parser()

    # Act / Assert
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["recompact", "--reset-compacted"])
    assert exc_info.value.code == 2


def test_recompact_cli_builds_request_and_emits_json(monkeypatch, capsys):
    """recompact CLIがselectorとJSON出力をserviceへ渡す。"""
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

    class FakeService:
        def __init__(self, **kwargs):
            captured["service_kwargs"] = kwargs

        def run(self, request):
            captured["request"] = request
            return SimpleNamespace(
                failed=0,
                to_dict=lambda: {"operation": "recompact", "status": "succeeded"},
            )

    monkeypatch.setattr(
        "pipelines.main.PipelinesConfig",
        lambda: SimpleNamespace(timezone="Asia/Tokyo"),
    )
    monkeypatch.setattr("pipelines.main._load_r2_config", lambda: r2_config)
    monkeypatch.setattr("pipelines.main.boto3.client", lambda *args, **kwargs: object())
    monkeypatch.setattr("pipelines.main.GoogleHealthWriter", FakeWriter)
    monkeypatch.setattr("pipelines.main.RecompactService", FakeService)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pipelines",
            "recompact",
            "--provider",
            "spotify",
            "--year",
            "2026",
            "--month",
            "8",
            "--prune",
            "--json",
        ],
    )

    # Act
    main()

    # Assert
    request = captured["request"]
    assert request.provider == "spotify"
    assert request.year == 2026
    assert request.month == 8
    assert request.prune is True
    assert json.loads(capsys.readouterr().out) == {
        "operation": "recompact",
        "status": "succeeded",
    }
