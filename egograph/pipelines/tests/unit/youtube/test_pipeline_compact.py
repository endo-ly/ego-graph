"""YouTube compact pipeline の単体テスト。"""

from unittest.mock import MagicMock

from pipelines.sources.common.config import Config, DuckDBConfig, R2Config
from pipelines.sources.youtube.pipeline import run_youtube_compact
from pipelines.workflows.registry import get_workflows
from pydantic import SecretStr


def _build_config() -> Config:
    return Config(
        duckdb=DuckDBConfig(
            r2=R2Config(
                endpoint_url="https://example.com",
                access_key_id="test-access-key",
                secret_access_key=SecretStr("test-secret-key"),
                bucket_name="test-bucket",
                raw_path="raw/",
                events_path="events/",
                master_path="master/",
            )
        )
    )


def test_run_youtube_compact_compacts_target_months(monkeypatch):
    """対象月ごとに compact_month が呼ばれる。"""
    fake_storage = MagicMock()
    fake_storage.compact_month.return_value = (
        "compacted/events/youtube/watch_events/year=2026/month=04/data.parquet"
    )

    monkeypatch.setattr(
        "pipelines.sources.youtube.pipeline.resolve_target_months",
        lambda _y, _m: [(2026, 4)],
    )
    monkeypatch.setattr(
        "pipelines.sources.youtube.pipeline.YouTubeStorage",
        lambda **_: fake_storage,
    )

    result = run_youtube_compact(config=_build_config())

    assert result["provider"] == "youtube"
    assert result["operation"] == "compact"
    assert len(result["compacted_keys"]) == 1
    fake_storage.compact_month.assert_called_once_with(year=2026, month=4)


def test_run_youtube_compact_skips_when_no_data(monkeypatch):
    """compact_month が None を返した場合は skipped に積む。"""
    fake_storage = MagicMock()
    fake_storage.compact_month.return_value = None

    monkeypatch.setattr(
        "pipelines.sources.youtube.pipeline.resolve_target_months",
        lambda _y, _m: [(2026, 1), (2026, 2)],
    )
    monkeypatch.setattr(
        "pipelines.sources.youtube.pipeline.YouTubeStorage",
        lambda **_: fake_storage,
    )

    result = run_youtube_compact(config=_build_config())

    assert result["compacted_keys"] == []
    assert result["skipped_targets"] == ["youtube:2026-01", "youtube:2026-02"]


def test_youtube_ingest_workflow_has_compact_step():
    """youtube_ingest_workflow に compact step が含まれる。"""
    workflows = get_workflows()
    yt_workflow = workflows["youtube_ingest_workflow"]
    step_ids = [s.step_id for s in yt_workflow.steps]
    assert "run_youtube_compact" in step_ids


def test_youtube_ingest_workflow_step_order():
    """ステップが ingest → compact の順で定義されている。"""
    workflows = get_workflows()
    yt_workflow = workflows["youtube_ingest_workflow"]
    step_ids = [s.step_id for s in yt_workflow.steps]
    assert step_ids.index("run_youtube_ingest") < step_ids.index("run_youtube_compact")
