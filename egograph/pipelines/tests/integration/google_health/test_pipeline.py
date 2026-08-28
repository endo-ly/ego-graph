"""Google Health取り込みの統合テスト。"""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import patch

import pandas as pd
from botocore.exceptions import ClientError

from pipelines.domain.workflow import (
    QueuedReason,
    TriggerType,
    WorkflowRun,
    WorkflowRunStatus,
)
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.sources.google_health.extractor import ExtractedGoogleHealthData
from pipelines.sources.google_health.models import OAuthToken, SyncStatus
from pipelines.sources.google_health.repository import GoogleHealthRepository
from pipelines.sources.google_health.workflow import (
    GoogleHealthWorkflowDependencies,
    run_google_health_compact,
    run_google_health_ingest,
)
from pipelines.sources.google_health.writer import GoogleHealthWriter


class MemoryS3:
    """統合テスト用in-memory S3。"""

    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        objects = self.objects

        class Paginator:
            def paginate(self, *, Bucket, Prefix):  # noqa: N803
                yield {
                    "Contents": [
                        {"Key": key} for key in objects if key.startswith(Prefix)
                    ]
                }

        return Paginator()


class FixtureExtractor:
    """3種類のrecordを返すfixture extractor。"""

    def extract(self, *, data_type, **kwargs):
        payloads = {
            "steps": {
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
                "dailyRollupResponses": [
                    {
                        "rollupDataPoints": [
                            {
                                "civilStartTime": {
                                    "date": {
                                        "year": 2026,
                                        "month": 6,
                                        "day": 1,
                                    }
                                },
                                "steps": {"countSum": "1000"},
                            }
                        ]
                    }
                ],
            },
            "heart-rate": {
                "reconcileResponses": [
                    {
                        "dataPoints": [
                            {
                                "heartRate": {
                                    "sampleTime": {
                                        "physicalTime": "2026-06-01T01:00:00Z"
                                    },
                                    "beatsPerMinute": 72,
                                }
                            }
                        ]
                    }
                ],
                "dailyRollupResponses": [],
            },
            "sleep": {
                "reconcileResponses": [
                    {
                        "dataPoints": [
                            {
                                "dataPointName": "sleep-1",
                                "sleep": {
                                    "interval": {
                                        "startTime": "2026-05-31T23:00:00Z",
                                        "endTime": "2026-06-01T07:00:00Z",
                                    },
                                    "type": "SLEEP",
                                },
                            }
                        ]
                    }
                ],
                "dailyRollupResponses": [],
            },
        }
        payload = payloads[data_type.name]
        count = sum(
            len(response.get("dataPoints", []))
            for response in payload["reconcileResponses"]
        ) + sum(
            len(response.get("rollupDataPoints", []))
            for response in payload["dailyRollupResponses"]
        )
        return ExtractedGoogleHealthData(payload=payload, record_count=count)


def _run():
    return WorkflowRun(
        run_id="f62ef091-9372-4e14-b129-55729525bd78",
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
                "data_types": ["steps", "heart-rate", "sleep"],
            }
        },
    )


def test_ingest_saves_raw_all_parquet_kinds_and_sync_state(
    tmp_path,
    monkeypatch,
):
    """1 runでRaw、5 Parquet、data type別sync結果を保存する。"""
    # Arrange
    conn = connect(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    repository = GoogleHealthRepository(conn)
    token = OAuthToken(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        token_type="Bearer",
        scopes=("scope",),
    )
    repository.save_connection(
        token=token,
        access_token_encrypted=b"encrypted-access",
        refresh_token_encrypted=b"encrypted-refresh",
    )
    memory_s3 = MemoryS3()
    with patch(
        "pipelines.sources.google_health.writer.boto3.client",
        return_value=memory_s3,
    ):
        writer = GoogleHealthWriter(
            endpoint_url="https://r2.example.test",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
        )
    monkeypatch.setattr(
        "pipelines.sources.google_health.workflow._build_dependencies",
        lambda: GoogleHealthWorkflowDependencies(
            repository=repository,
            extractor=FixtureExtractor(),
            writer=writer,
        ),
    )

    # Act
    ingest_result = run_google_health_ingest(_run())
    compact_result = run_google_health_compact(_run())

    # Assert
    assert ingest_result["status"] == "succeeded"
    assert compact_result["status"] == "succeeded"
    raw_keys = [key for key in memory_s3.objects if key.startswith("raw/")]
    assert len(raw_keys) == 3
    for dataset in ("records", "daily_metrics", "samples", "intervals"):
        event_key = (
            f"events/google_health/{dataset}/year=2026/month=06/"
            "f62ef091-9372-4e14-b129-55729525bd78.parquet"
        )
        compacted_key = (
            f"compacted/events/google_health/{dataset}/year=2026/month=06/data.parquet"
        )
        assert event_key in memory_s3.objects
        assert compacted_key in memory_s3.objects
        assert not pd.read_parquet(BytesIO(memory_s3.objects[compacted_key])).empty
    session_prefix = "events/google_health/sessions/year=2026/month=05/"
    session_keys = [key for key in memory_s3.objects if key.startswith(session_prefix)]
    assert len(session_keys) == 1
    assert not pd.read_parquet(BytesIO(memory_s3.objects[session_keys[0]])).empty
    compacted_session_key = (
        "compacted/events/google_health/sessions/year=2026/month=05/data.parquet"
    )
    assert compacted_session_key in memory_s3.objects
    for data_type in ("steps", "heart-rate", "sleep"):
        cursor = repository.get_sync_cursor("google-health-primary", data_type)
        assert cursor is not None
        assert cursor.status is SyncStatus.SUCCESS
        assert cursor.record_count > 0
