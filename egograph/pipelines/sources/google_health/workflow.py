"""Google Health ingestion workflow。"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import SecretStr

from pipelines.config import PipelinesConfig
from pipelines.domain.workflow import WorkflowRun
from pipelines.infrastructure.db.connection import connect
from pipelines.infrastructure.db.schema import initialize_schema
from pipelines.sources.common.settings import PipelinesSettings
from pipelines.sources.google_health.client import GoogleHealthAPIClient
from pipelines.sources.google_health.data_types import DATA_TYPE_BY_NAME, DATA_TYPES
from pipelines.sources.google_health.extractor import GoogleHealthExtractor
from pipelines.sources.google_health.models import (
    ConnectionStatus,
    GoogleHealthIngestRequest,
    GoogleHealthRunMode,
    GoogleHealthSyncCursor,
    SyncStatus,
)
from pipelines.sources.google_health.normalizer import (
    aggregate_daily_metrics,
    normalize_google_health_payload,
)
from pipelines.sources.google_health.repository import GoogleHealthRepository
from pipelines.sources.google_health.token_cipher import TokenCipher
from pipelines.sources.google_health.writer import GoogleHealthWriter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoogleHealthWorkflowDependencies:
    """workflow実行に必要なadapter群。"""

    repository: GoogleHealthRepository
    extractor: GoogleHealthExtractor
    writer: GoogleHealthWriter
    timezone: ZoneInfo = ZoneInfo("UTC")
    db_connection: sqlite3.Connection | None = None


def run_google_health_ingest(run: WorkflowRun) -> dict[str, object]:
    """Google Healthの対象data typeを取得しRaw/eventsへ保存する。"""
    dependencies = _build_dependencies()
    try:
        return _execute_google_health_ingest(run, dependencies)
    finally:
        if dependencies.db_connection is not None:
            dependencies.db_connection.close()


def _execute_google_health_ingest(
    run: WorkflowRun,
    dependencies: GoogleHealthWorkflowDependencies,
) -> dict[str, object]:
    """解決済みadapterを使ってGoogle Health取り込みを実行する。"""
    request = _parse_request(run)
    connection = dependencies.repository.get_connection()
    if connection is None or connection.status is not ConnectionStatus.ACTIVE:
        raise RuntimeError("google_health_active_connection_not_found")

    records: dict[str, list[dict]] = {
        "daily_metrics": [],
        "samples": [],
        "intervals": [],
        "sessions": [],
    }
    results: list[dict[str, object]] = []
    completed_data_types: list[str] = []

    for data_type_name in request.data_types:
        data_type = DATA_TYPE_BY_NAME[data_type_name]
        try:
            extracted = dependencies.extractor.extract(
                connection_id=connection.connection_id,
                data_type=data_type,
                date_from=request.date_from,
                date_to=request.date_to,
            )
            raw_ref = dependencies.writer.save_raw(
                connection_id=connection.connection_id,
                data_type=data_type.name,
                date_from=request.date_from,
                date_to=request.date_to,
                run_id=run.run_id,
                payload=extracted.payload,
            )
            normalized = normalize_google_health_payload(
                connection_id=connection.connection_id,
                data_type=data_type,
                payload=extracted.payload,
                raw_ref=raw_ref,
                timezone=dependencies.timezone,
            )
            normalized_count = sum(len(rows) for rows in normalized.values())
            if extracted.record_count > 0 and normalized_count == 0:
                raise ValueError("google_health_normalization_produced_no_records")
            for dataset, rows in normalized.items():
                records[dataset].extend(rows)
            status = (
                SyncStatus.SUCCESS if extracted.record_count > 0 else SyncStatus.NO_DATA
            )
            completed_data_types.append(data_type.name)
            results.append(
                {
                    "data_type": data_type.name,
                    "status": status.value,
                    "record_count": normalized_count,
                    "raw_ref": raw_ref,
                }
            )
        except Exception as exc:
            logger.exception(
                "Google Health data type ingest failed: data_type=%s",
                data_type.name,
            )
            results.append(
                {
                    "data_type": data_type.name,
                    "status": SyncStatus.FAILED.value,
                    "record_count": 0,
                    "error": _short_error(exc),
                }
            )

    records["daily_metrics"] = aggregate_daily_metrics(records["daily_metrics"])
    saved_keys: list[str] = []
    if completed_data_types:
        try:
            saved_keys = dependencies.writer.save_events(
                run_id=run.run_id,
                records=records,
            )
        except Exception as exc:
            logger.exception("Google Health events保存に失敗しました")
            error = _short_error(exc)
            for result in results:
                if result["data_type"] in completed_data_types:
                    result.update(
                        status=SyncStatus.FAILED.value,
                        record_count=0,
                        error=error,
                    )

    for result in results:
        status = SyncStatus(str(result["status"]))
        dependencies.repository.save_sync_result(
            connection_id=connection.connection_id,
            data_type=str(result["data_type"]),
            status=status,
            range_start=request.date_from,
            range_end=request.date_to,
            run_id=run.run_id,
            record_count=int(result["record_count"]),
            error_message=str(result["error"]) if "error" in result else None,
        )

    return {
        "provider": "google_health",
        "operation": "ingest",
        "status": _run_status(results),
        "request": _request_summary(request),
        "data_types": results,
        "saved_keys": saved_keys,
        "record_count": sum(int(result["record_count"]) for result in results),
        "errors": _result_errors(results),
    }


def run_google_health_compact(run: WorkflowRun) -> dict[str, object]:
    """今回runのeventsを対象期間のcompacted Parquetへ反映する。"""
    dependencies = _build_dependencies()
    try:
        return _execute_google_health_compact(run, dependencies)
    finally:
        if dependencies.db_connection is not None:
            dependencies.db_connection.close()


def _execute_google_health_compact(
    run: WorkflowRun,
    dependencies: GoogleHealthWorkflowDependencies,
) -> dict[str, object]:
    """同期結果を基に成功したdata typeだけをcompactする。"""
    request = _parse_request(run)
    connection = dependencies.repository.get_connection()
    if connection is None or connection.status is not ConnectionStatus.ACTIVE:
        raise RuntimeError("google_health_active_connection_not_found")

    cursors = dependencies.repository.list_sync_results_for_run(
        connection.connection_id,
        run.run_id,
    )
    results = _cursor_results(request, cursors)
    completed_data_types = tuple(
        str(result["data_type"])
        for result in results
        if result["status"] in {SyncStatus.SUCCESS.value, SyncStatus.NO_DATA.value}
    )
    compacted_keys: list[str] = []
    if completed_data_types:
        try:
            compacted_keys = dependencies.writer.compact_range(
                connection_id=connection.connection_id,
                selected_data_types=completed_data_types,
                date_from=request.date_from,
                date_to=request.date_to,
                run_id=run.run_id,
            )
        except Exception as exc:
            logger.exception("Google Health compactionに失敗しました")
            error = _short_error(exc)
            for result in results:
                if result["data_type"] not in completed_data_types:
                    continue
                result.update(
                    status=SyncStatus.FAILED.value,
                    error=error,
                )
                dependencies.repository.save_sync_result(
                    connection_id=connection.connection_id,
                    data_type=str(result["data_type"]),
                    status=SyncStatus.FAILED,
                    range_start=request.date_from,
                    range_end=request.date_to,
                    run_id=run.run_id,
                    record_count=int(result["record_count"]),
                    error_message=error,
                )

    return {
        "provider": "google_health",
        "operation": "compact",
        "status": _run_status(results),
        "request": _request_summary(request),
        "data_types": results,
        "compacted_keys": compacted_keys,
        "record_count": sum(int(result["record_count"]) for result in results),
        "errors": _result_errors(results),
    }


def _cursor_results(
    request: GoogleHealthIngestRequest,
    cursors: list[GoogleHealthSyncCursor],
) -> list[dict[str, object]]:
    cursors_by_type = {cursor.data_type: cursor for cursor in cursors}
    results: list[dict[str, object]] = []
    for data_type in request.data_types:
        cursor = cursors_by_type.get(data_type)
        if cursor is None:
            results.append(
                {
                    "data_type": data_type,
                    "status": SyncStatus.FAILED.value,
                    "record_count": 0,
                    "error": "sync_result_not_found",
                }
            )
            continue
        result: dict[str, object] = {
            "data_type": cursor.data_type,
            "status": cursor.status.value,
            "record_count": cursor.record_count,
        }
        if cursor.last_error_message:
            result["error"] = cursor.last_error_message
        results.append(result)
    return results


def _request_summary(request: GoogleHealthIngestRequest) -> dict[str, object]:
    return {
        "mode": request.mode.value,
        "from": request.date_from.isoformat(),
        "to": request.date_to.isoformat(),
        "data_types": list(request.data_types),
    }


def _run_status(results: list[dict[str, object]]) -> str:
    failed_count = sum(
        result["status"] == SyncStatus.FAILED.value for result in results
    )
    if failed_count == len(results):
        return "failed"
    if failed_count:
        return "partial_failed"
    return "succeeded"


def _result_errors(results: list[dict[str, object]]) -> list[str]:
    return [
        f"{result['data_type']}: {result['error']}"
        for result in results
        if "error" in result
    ]


def _parse_request(run: WorkflowRun) -> GoogleHealthIngestRequest:
    summary = run.result_summary or {}
    raw = summary.get("request")
    if not isinstance(raw, dict):
        raise ValueError("invalid_request: Google Health run input is required")
    try:
        mode = GoogleHealthRunMode(str(raw["mode"]))
        date_from = date.fromisoformat(str(raw["from"]))
        date_to = date.fromisoformat(str(raw["to"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid_request: invalid mode or range") from exc
    if date_from >= date_to:
        raise ValueError("invalid_range: from must be earlier than to")

    requested_types = raw.get("data_types")
    if requested_types:
        if not isinstance(requested_types, list):
            raise ValueError("invalid_data_types: list is required")
        unknown = set(requested_types) - DATA_TYPE_BY_NAME.keys()
        if unknown:
            raise ValueError(
                f"invalid_data_types: unsupported values: {', '.join(sorted(unknown))}"
            )
        data_types = tuple(dict.fromkeys(str(item) for item in requested_types))
    else:
        data_types = tuple(item.name for item in DATA_TYPES)
    return GoogleHealthIngestRequest(
        mode=mode,
        date_from=date_from,
        date_to=date_to,
        data_types=data_types,
    )


def _build_dependencies() -> GoogleHealthWorkflowDependencies:
    config = PipelinesConfig()
    if not config.google_health_is_configured:
        raise ValueError("google_health_oauth_configuration_required")
    conn = connect(config.database_path)
    try:
        initialize_schema(conn)
        repository = GoogleHealthRepository(conn)
        encryption_key = cast(SecretStr, config.google_health_token_encryption_key)
        client_id = cast(SecretStr, config.google_health_client_id)
        client_secret = cast(SecretStr, config.google_health_client_secret)
        cipher = TokenCipher(encryption_key.get_secret_value())
        client = GoogleHealthAPIClient(
            repository,
            cipher,
            client_id=client_id.get_secret_value(),
            client_secret=client_secret.get_secret_value(),
            timezone=ZoneInfo(config.timezone),
        )

        source_config = PipelinesSettings.load()
        if source_config.duckdb is None or source_config.duckdb.r2 is None:
            raise ValueError("R2 configuration is required for google health pipeline")
        r2 = source_config.duckdb.r2
        return GoogleHealthWorkflowDependencies(
            repository=repository,
            extractor=GoogleHealthExtractor(
                client,
                timezone=ZoneInfo(config.timezone),
            ),
            writer=GoogleHealthWriter(
                endpoint_url=r2.endpoint_url,
                access_key_id=r2.access_key_id,
                secret_access_key=r2.secret_access_key.get_secret_value(),
                bucket_name=r2.bucket_name,
                raw_path=r2.raw_path,
                events_path=r2.events_path,
                timezone=ZoneInfo(config.timezone),
            ),
            timezone=ZoneInfo(config.timezone),
            db_connection=conn,
        )
    except Exception:
        conn.close()
        raise


def _short_error(exc: Exception) -> str:
    message = next(
        (line.strip() for line in str(exc).splitlines() if line.strip()),
        None,
    )
    return message or exc.__class__.__name__
