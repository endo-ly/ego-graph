"""FastAPI dependencies."""

from fastapi import Request

from pipelines.service import PipelineService


def get_service(request: Request) -> PipelineService:
    """app.state.service から PipelineService を取得する。"""
    return request.app.state.service
