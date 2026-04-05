"""FastAPI dependencies."""

import secrets

from fastapi import Depends, Header, HTTPException, Request

from pipelines.service import PipelineService


def get_service(request: Request) -> PipelineService:
    """app.state.service から PipelineService を取得する。"""
    return request.app.state.service


def verify_api_key(
    x_api_key: str | None = Header(None),
    service: PipelineService = Depends(get_service),
) -> None:
    """X-API-Key を検証する。PIPELINES_API_KEY の設定が必須。"""
    api_key = service.config.api_key
    if api_key is None:
        raise HTTPException(
            status_code=500, detail="PIPELINES_API_KEY is not configured"
        )

    if not x_api_key or not secrets.compare_digest(
        x_api_key,
        api_key.get_secret_value(),
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")
