"""Run management API."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from pipelines.api.dependencies import get_service
from pipelines.domain.errors import PipelinesError
from pipelines.service import PipelineService

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.get("")
def list_runs(service: PipelineService = Depends(get_service)) -> list[dict]:
    """run 一覧を取得する。"""
    return [run.__dict__ for run in service.list_runs()]


@router.get("/{run_id}")
def get_run(run_id: str, service: PipelineService = Depends(get_service)) -> dict:
    """run 詳細を取得する。"""
    try:
        detail = service.get_run_detail(run_id)
        return {
            "run": detail["run"].__dict__,
            "steps": [step.__dict__ for step in detail["steps"]],
        }
    except PipelinesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{run_id}/steps/{step_id}/log", response_class=PlainTextResponse)
def get_step_log(
    run_id: str,
    step_id: str,
    service: PipelineService = Depends(get_service),
) -> str:
    """step ログ本文を取得する。"""
    try:
        return service.get_step_log(run_id, step_id)
    except PipelinesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{run_id}/retry", status_code=201)
def retry_run(
    run_id: str,
    service: PipelineService = Depends(get_service),
) -> dict:
    """再実行 run を queue に積む。"""
    try:
        return service.retry_run(run_id).__dict__
    except PipelinesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{run_id}/cancel")
def cancel_run(
    run_id: str,
    service: PipelineService = Depends(get_service),
) -> dict:
    """queued run を cancel する。"""
    try:
        return service.cancel_run(run_id).__dict__
    except PipelinesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
