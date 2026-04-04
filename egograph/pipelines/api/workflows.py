"""Workflow management API."""

from fastapi import APIRouter, Depends, HTTPException

from pipelines.api.dependencies import get_service
from pipelines.domain.errors import PipelinesError
from pipelines.service import PipelineService

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


@router.get("")
def list_workflows(
    service: PipelineService = Depends(get_service),
) -> list[dict]:
    """workflow 一覧を取得する。"""
    return service.list_workflows()


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: str,
    service: PipelineService = Depends(get_service),
) -> dict:
    """workflow 詳細を取得する。"""
    try:
        return service.get_workflow(workflow_id)
    except PipelinesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{workflow_id}/runs")
def list_workflow_runs(
    workflow_id: str,
    service: PipelineService = Depends(get_service),
) -> list[dict]:
    """指定 workflow の run 一覧を取得する。"""
    return [run.__dict__ for run in service.list_runs(workflow_id=workflow_id)]


@router.post("/{workflow_id}/runs", status_code=201)
def create_workflow_run(
    workflow_id: str,
    service: PipelineService = Depends(get_service),
) -> dict:
    """手動 run を queue に積む。"""
    try:
        return service.trigger_workflow(workflow_id).__dict__
    except PipelinesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{workflow_id}/enable")
def enable_workflow(
    workflow_id: str,
    service: PipelineService = Depends(get_service),
) -> dict:
    """workflow を有効化する。"""
    try:
        return service.set_workflow_enabled(workflow_id, True)
    except PipelinesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{workflow_id}/disable")
def disable_workflow(
    workflow_id: str,
    service: PipelineService = Depends(get_service),
) -> dict:
    """workflow を無効化する。"""
    try:
        return service.set_workflow_enabled(workflow_id, False)
    except PipelinesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
