"""Pipelines service CLI and HTTP entrypoint."""

from __future__ import annotations

import argparse
import json
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import uvicorn

from pipelines.app import create_app
from pipelines.config import PipelinesConfig
from pipelines.maintenance.recompact import RecompactRequest, RecompactService
from pipelines.service import PipelineService
from pipelines.sources.common.config import R2Config
from pipelines.sources.common.settings import PipelinesSettings
from pipelines.sources.google_health.writer import GoogleHealthWriter


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, default=_json_default, ensure_ascii=False, indent=2))
        return
    if isinstance(payload, list):
        for item in payload:
            print(item)
        return
    print(payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipelines")
    subparsers = parser.add_subparsers(dest="command", required=False)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)

    workflow_parser = subparsers.add_parser("workflow")
    workflow_sub = workflow_parser.add_subparsers(
        dest="workflow_command",
        required=True,
    )
    workflow_list_parser = workflow_sub.add_parser("list")
    workflow_list_parser.add_argument("--json", action="store_true")
    workflow_run_parser = workflow_sub.add_parser("run")
    workflow_run_parser.add_argument("workflow_id")
    workflow_run_parser.add_argument("--json", action="store_true")
    workflow_enable_parser = workflow_sub.add_parser("enable")
    workflow_enable_parser.add_argument("workflow_id")
    workflow_enable_parser.add_argument("--json", action="store_true")
    workflow_disable_parser = workflow_sub.add_parser("disable")
    workflow_disable_parser.add_argument("workflow_id")
    workflow_disable_parser.add_argument("--json", action="store_true")

    recompact_parser = subparsers.add_parser(
        "recompact",
        help="Dataset Catalogのsourceからcompacted Datasetを再構築する",
    )
    recompact_parser.add_argument("--provider")
    recompact_parser.add_argument("--dataset", dest="dataset_id")
    recompact_parser.add_argument("--year", type=int)
    recompact_parser.add_argument("--month", type=int)
    recompact_parser.add_argument("--prune", action="store_true")
    recompact_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run")
    run_sub = run_parser.add_subparsers(dest="run_command", required=True)
    run_list_parser = run_sub.add_parser("list")
    run_list_parser.add_argument("--json", action="store_true")
    run_show_parser = run_sub.add_parser("show")
    run_show_parser.add_argument("run_id")
    run_show_parser.add_argument("--json", action="store_true")
    run_log_parser = run_sub.add_parser("log")
    run_log_parser.add_argument("run_id")
    run_log_parser.add_argument("step_id")
    run_retry_parser = run_sub.add_parser("retry")
    run_retry_parser.add_argument("run_id")
    run_retry_parser.add_argument("--json", action="store_true")
    run_cancel_parser = run_sub.add_parser("cancel")
    run_cancel_parser.add_argument("run_id")
    run_cancel_parser.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    """CLI コマンドを実行する。"""
    args = _build_parser().parse_args()
    config = PipelinesConfig()
    if args.command in (None, "serve"):
        app = create_app(config)
        uvicorn.run(
            app,
            host=args.host or config.host,
            port=args.port or config.port,
        )
        return

    if args.command == "recompact":
        r2_config = _load_r2_config()
        config = PipelinesConfig()
        s3_client = boto3.client(
            "s3",
            endpoint_url=r2_config.endpoint_url,
            aws_access_key_id=r2_config.access_key_id,
            aws_secret_access_key=r2_config.secret_access_key.get_secret_value(),
            region_name="auto",
        )
        google_health_writer = GoogleHealthWriter(
            endpoint_url=r2_config.endpoint_url,
            access_key_id=r2_config.access_key_id,
            secret_access_key=r2_config.secret_access_key.get_secret_value(),
            bucket_name=r2_config.bucket_name,
            raw_path=r2_config.raw_path,
            events_path=r2_config.events_path,
            timezone=ZoneInfo(config.timezone),
        )
        result = RecompactService(
            s3_client=s3_client,
            bucket_name=r2_config.bucket_name,
            events_path=r2_config.events_path,
            master_path=r2_config.master_path,
            google_health_writer=google_health_writer,
        ).run(
            RecompactRequest(
                provider=args.provider,
                dataset_id=args.dataset_id,
                year=args.year,
                month=args.month,
                prune=args.prune,
            )
        )
        _emit(result.to_dict(), args.json)
        if result.failed:
            raise SystemExit(1)
        return

    service = PipelineService.create(config)
    if args.command == "workflow" and args.workflow_command == "list":
        _emit(service.list_workflows(), args.json)
        return
    if args.command == "workflow" and args.workflow_command == "run":
        _emit(service.trigger_workflow(args.workflow_id).__dict__, args.json)
        return
    if args.command == "workflow" and args.workflow_command == "enable":
        _emit(service.set_workflow_enabled(args.workflow_id, True), args.json)
        return
    if args.command == "workflow" and args.workflow_command == "disable":
        _emit(service.set_workflow_enabled(args.workflow_id, False), args.json)
        return
    if args.command == "run" and args.run_command == "list":
        _emit([run.__dict__ for run in service.list_runs()], args.json)
        return
    if args.command == "run" and args.run_command == "show":
        detail = service.get_run_detail(args.run_id)
        _emit(
            {
                "run": detail["run"].__dict__,
                "steps": [step.__dict__ for step in detail["steps"]],
                "duration_seconds": detail["duration_seconds"],
            },
            args.json,
        )
        return
    if args.command == "run" and args.run_command == "log":
        print(service.get_step_log(args.run_id, args.step_id))
        return
    if args.command == "run" and args.run_command == "retry":
        _emit(service.retry_run(args.run_id).__dict__, args.json)
        return
    if args.command == "run" and args.run_command == "cancel":
        _emit(service.cancel_run(args.run_id).__dict__, args.json)


def _load_r2_config() -> R2Config:
    """CLI用のR2設定を読み込み、未設定を明示的なエラーにする。"""
    source_config = PipelinesSettings.load()
    if source_config.duckdb is None or source_config.duckdb.r2 is None:
        raise ValueError("invalid_r2_config: R2 settings are required")
    return source_config.duckdb.r2


if __name__ == "__main__":
    main()
