"""Google Health ingestion workflowのテスト。"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from pipelines.domain.workflow import (
    QueuedReason,
    TriggerType,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.sources.google_health.extractor import ExtractedGoogleHealthData
from pipelines.sources.google_health.models import (
    ConnectionStatus,
    GoogleHealthConnection,
    GoogleHealthSyncCursor,
    SyncStatus,
)
from pipelines.sources.google_health.workflow import (
    GoogleHealthWorkflowDependencies,
    _parse_request,
    _short_error,
    run_google_health_compact,
    run_google_health_ingest,
)


def _run(data_types):
    return WorkflowRun(
        run_id="run-1",
        workflow_id="google_health_ingest_workflow",
        trigger_type=TriggerType.MANUAL,
        queued_reason=QueuedReason.MANUAL_REQUEST,
        status=WorkflowRunStatus.RUNNING,
        scheduled_at=None,
        queued_at=datetime(2026, 6, 4, tzinfo=UTC),
        started_at=datetime(2026, 6, 4, tzinfo=UTC),
        finished_at=None,
        last_error_message=None,
        requested_by="api",
        parent_run_id=None,
        result_summary={
            "request": {
                "mode": "data_type_range",
                "from": "2026-06-01",
                "to": "2026-06-03",
                "data_types": data_types,
            }
        },
    )


class FakeRepository:
    def __init__(self):
        self.sync_results = []

    def get_connection(self):
        return GoogleHealthConnection(
            connection_id="google-health-primary",
            status=ConnectionStatus.ACTIVE,
            scopes=(),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
            updated_at=datetime(2026, 6, 1, tzinfo=UTC),
            last_error_message=None,
        )

    def save_sync_result(self, **kwargs):
        self.sync_results.append(kwargs)

    def list_sync_results_for_run(self, connection_id, run_id):
        return [
            GoogleHealthSyncCursor(
                connection_id=item["connection_id"],
                data_type=item["data_type"],
                cursor=item.get("cursor"),
                status=item["status"],
                range_start=item["range_start"],
                range_end=item["range_end"],
                last_run_id=item["run_id"],
                record_count=item["record_count"],
                last_error_message=item["error_message"],
                updated_at=datetime(2026, 6, 4, tzinfo=UTC),
            )
            for item in self.sync_results
            if item["connection_id"] == connection_id and item["run_id"] == run_id
        ]


class FakeExtractor:
    def extract(self, *, data_type, **kwargs):
        if data_type.name == "sleep":
            raise RuntimeError("sleep unavailable")
        return ExtractedGoogleHealthData(
            payload={
                "reconcileResponses": [
                    {
                        "dataPoints": [
                            {
                                "steps": {
                                    "interval": {
                                        "startTime": "2026-06-01T00:00:00Z",
                                        "endTime": "2026-06-01T00:05:00Z",
                                    },
                                    "count": 120,
                                }
                            }
                        ]
                    }
                ],
                "dailyRollupResponses": [],
            },
            record_count=1,
        )


class FakeWriter:
    def __init__(self):
        self.event_calls = []
        self.compact_calls = []

    def save_raw(self, **kwargs):
        return f"raw/{kwargs['data_type']}.json"

    def save_events(self, **kwargs):
        self.event_calls.append(kwargs)
        return ["events/google_health/intervals/year=2026/month=06/run-1.parquet"]

    def compact_range(self, **kwargs):
        self.compact_calls.append(kwargs)
        return [
            "compacted/events/google_health/intervals/year=2026/month=06/data.parquet"
        ]


def _dependencies(repository, writer, extractor=None):
    return GoogleHealthWorkflowDependencies(
        repository=repository,
        extractor=extractor or FakeExtractor(),
        writer=writer,
    )


def test_partial_failure_saves_successful_events_and_sync_results(monkeypatch):
    """一部失敗時も成功data typeのeventsと各sync結果を保存する。"""
    # Arrange
    repository = FakeRepository()
    writer = FakeWriter()
    monkeypatch.setattr(
        "pipelines.sources.google_health.workflow._build_dependencies",
        lambda: _dependencies(repository, writer),
    )

    # Act
    result = run_google_health_ingest(_run(["steps", "sleep"]))

    # Assert
    assert result["status"] == "partial_failed"
    assert result["record_count"] == 1
    assert len(writer.event_calls) == 1
    assert [item["status"] for item in repository.sync_results] == [
        SyncStatus.SUCCESS,
        SyncStatus.FAILED,
    ]
    assert [item["record_count"] for item in repository.sync_results] == [1, 0]


def test_no_data_is_successful_and_writes_no_event_file(monkeypatch):
    """データ0件はno_dataとして正常終了しeventsを作らない。"""
    # Arrange
    repository = FakeRepository()
    writer = FakeWriter()

    class EmptyExtractor:
        def extract(self, **kwargs):
            return ExtractedGoogleHealthData(
                payload={
                    "reconcileResponses": [{"dataPoints": []}],
                    "dailyRollupResponses": [],
                },
                record_count=0,
            )

    monkeypatch.setattr(
        "pipelines.sources.google_health.workflow._build_dependencies",
        lambda: _dependencies(repository, writer, EmptyExtractor()),
    )

    # Act
    result = run_google_health_ingest(_run(["steps"]))

    # Assert
    assert result["status"] == "succeeded"
    assert result["data_types"][0]["status"] == "no_data"
    assert writer.event_calls[0]["records"]["intervals"] == []


def test_save_failure_reports_zero_saved_records(monkeypatch):
    """events保存失敗時はメモリ上の正規化件数を返さない。"""
    repository = FakeRepository()

    class FailingWriter(FakeWriter):
        def save_events(self, **kwargs):
            raise RuntimeError("save failed")

    monkeypatch.setattr(
        "pipelines.sources.google_health.workflow._build_dependencies",
        lambda: _dependencies(repository, FailingWriter()),
    )

    result = run_google_health_ingest(_run(["steps"]))

    assert result["status"] == "failed"
    assert result["record_count"] == 0


def test_compact_uses_only_successful_and_no_data_types(monkeypatch):
    """失敗data typeを除外して成功・no_dataの範囲だけ置換する。"""
    # Arrange
    repository = FakeRepository()
    writer = FakeWriter()
    for data_type, status, count, error in (
        ("steps", SyncStatus.SUCCESS, 1, None),
        ("heart-rate", SyncStatus.NO_DATA, 0, None),
        ("sleep", SyncStatus.FAILED, 0, "sleep unavailable"),
    ):
        repository.save_sync_result(
            connection_id="google-health-primary",
            data_type=data_type,
            status=status,
            range_start=date(2026, 6, 1),
            range_end=date(2026, 6, 3),
            run_id="run-1",
            record_count=count,
            error_message=error,
        )
    monkeypatch.setattr(
        "pipelines.sources.google_health.workflow._build_dependencies",
        lambda: _dependencies(repository, writer),
    )

    # Act
    result = run_google_health_compact(_run(["steps", "heart-rate", "sleep"]))

    # Assert
    assert result["status"] == "partial_failed"
    assert writer.compact_calls[0]["selected_data_types"] == (
        "steps",
        "heart-rate",
    )
    assert result["compacted_keys"] == [
        "compacted/events/google_health/intervals/year=2026/month=06/data.parquet"
    ]


def test_unrecognized_non_empty_payload_is_failed(monkeypatch):
    """API件数があるのに正規化0件なら成功扱いにしない。"""
    # Arrange
    repository = FakeRepository()
    writer = FakeWriter()

    class UnrecognizedExtractor:
        def extract(self, **kwargs):
            return ExtractedGoogleHealthData(
                payload={
                    "reconcileResponses": [{"dataPoints": [{"steps": {}}]}],
                    "dailyRollupResponses": [],
                },
                record_count=1,
            )

    monkeypatch.setattr(
        "pipelines.sources.google_health.workflow._build_dependencies",
        lambda: _dependencies(repository, writer, UnrecognizedExtractor()),
    )

    # Act
    result = run_google_health_ingest(_run(["steps"]))

    # Assert
    assert result["status"] == "failed"
    assert result["data_types"][0]["status"] == "failed"
    assert writer.event_calls == []


def test_short_error_falls_back_to_exception_class_for_empty_message():
    """例外メッセージが空でもclass名を返す。"""
    # Act
    result = _short_error(RuntimeError())

    # Assert
    assert result == "RuntimeError"


def test_parse_repair_request_uses_scheduled_time_in_configured_timezone():
    """repair期間はscheduled_atをTIMEZONEのローカル日付として解決する。"""
    run = _run(["steps"])
    run = WorkflowRun(
        **{
            **run.__dict__,
            "scheduled_at": datetime(2026, 6, 1, 15, 30, tzinfo=UTC),
            "result_summary": {"request": {"repair_days": 14}},
        }
    )

    request = _parse_request(run, ZoneInfo("Asia/Tokyo"))

    assert request.date_from == date(2026, 5, 20)
    assert request.date_to == date(2026, 6, 3)
    assert request.data_types
