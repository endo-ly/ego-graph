"""PipelineService のテスト。

retry_run, cancel_run, get_step_log などの運用機能を検証する。
"""

from pipelines.compaction import DatasetCompactionTarget
from pipelines.config import PipelinesConfig
from pipelines.domain.errors import WorkflowNotFoundError, WorkflowRunNotFoundError
from pipelines.domain.workflow import StepRunStatus
from pipelines.service import PipelineService
from pydantic import SecretStr


def _make_service(tmp_path, api_key: str | None = None) -> PipelineService:
    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=60,
        api_key=SecretStr(api_key) if api_key else None,
    )
    return PipelineService.create(config)


def test_retry_run_creates_new_queued_run(tmp_path):
    """失敗 run のリトライは新しい queued run を作成する。"""
    service = _make_service(tmp_path)

    # 手動 run を作成
    original_run = service.trigger_workflow("spotify_ingest_workflow")
    assert original_run.status == "queued"

    # リトライ実行
    retry_run = service.retry_run(original_run.run_id)
    assert retry_run.status == "queued"
    assert retry_run.workflow_id == "spotify_ingest_workflow"
    assert retry_run.parent_run_id == original_run.run_id


def test_retry_run_preserves_original_input(tmp_path):
    """入力付きrunのretryは元のresult_summaryを引き継ぐ。"""
    service = _make_service(tmp_path)
    original_run = service.trigger_google_health_ingest(
        {
            "mode": "range",
            "from": "2026-06-01",
            "to": "2026-06-03",
            "data_types": [],
        }
    )

    retry_run = service.retry_run(original_run.run_id)

    assert retry_run.result_summary == original_run.result_summary


def test_trigger_compaction_queues_dataset_targets(tmp_path):
    """manual compaction run は対象datasetをresult_summaryへ保存する。"""
    service = _make_service(tmp_path)
    targets = (
        DatasetCompactionTarget("github.commits", 2026, 7),
        DatasetCompactionTarget("github.pull_requests", 2026, 7),
    )

    run = service.trigger_compaction(targets)

    assert run.workflow_id == "github_compact_workflow"
    assert run.result_summary == {
        "compaction_targets": [
            {"dataset_id": "github.commits", "year": 2026, "month": 7},
            {"dataset_id": "github.pull_requests", "year": 2026, "month": 7},
        ]
    }


def test_trigger_compaction_rejects_mixed_provider_targets(tmp_path):
    """providerを跨ぐ対象はprovider lockを保てないため拒否する。"""
    service = _make_service(tmp_path)
    targets = (
        DatasetCompactionTarget("github.commits", 2026, 7),
        DatasetCompactionTarget("spotify.plays", 2026, 7),
    )

    try:
        service.trigger_compaction(targets)
        raise AssertionError("ValueError was not raised")
    except ValueError as exc:
        assert "same provider" in str(exc)


def test_retry_run_404_for_unknown_run(tmp_path):
    """存在しない run_id のリトライは例外を送出する。"""
    service = _make_service(tmp_path)

    try:
        service.retry_run("nonexistent-run-id")
        raise AssertionError("Should have raised WorkflowRunNotFoundError")
    except WorkflowRunNotFoundError:
        pass


def test_cancel_run_cancels_queued_run(tmp_path):
    """queued run のキャンセルは状態を canceled に更新する。"""
    service = _make_service(tmp_path)

    run = service.trigger_workflow("spotify_ingest_workflow")
    assert run.status == "queued"

    cancelled = service.cancel_run(run.run_id)
    assert cancelled.status == "canceled"


def test_cancel_run_404_for_unknown_run(tmp_path):
    """存在しない run_id のキャンセルは例外を送出する。"""
    service = _make_service(tmp_path)

    try:
        service.cancel_run("nonexistent-run-id")
        raise AssertionError("Should have raised WorkflowRunNotFoundError")
    except WorkflowRunNotFoundError:
        pass


def test_get_step_log_returns_log_content(tmp_path):
    """step ログが存在する場合、その内容を返す。"""
    service = _make_service(tmp_path)

    # ログファイルを作成
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    step_log_path = logs_dir / "test-step.log"
    step_log_path.write_text("test log line 1\ntest log line 2\n")

    # run と step を作成
    run = service.trigger_workflow("spotify_ingest_workflow")
    step = service.step_run_repository.insert_step_run(
        run_id=run.run_id,
        step_id="test-step",
        step_name="Test step",
        sequence_no=1,
        attempt_no=1,
        command="echo test",
    )
    service.step_run_repository.update_step_result(
        step_run_id=step.step_run_id,
        status=StepRunStatus.SUCCEEDED,
        log_path=str(step_log_path),
    )

    log_content = service.get_step_log(run.run_id, "test-step")
    assert "test log line 1" in log_content
    assert "test log line 2" in log_content


def test_get_step_log_404_for_missing_step(tmp_path):
    """存在しない step のログ取得は例外を送出する。"""
    service = _make_service(tmp_path)

    try:
        service.get_step_log("nonexistent-run-id", "nonexistent-step-id")
        raise AssertionError("Should have raised WorkflowNotFoundError")
    except WorkflowNotFoundError:
        pass
