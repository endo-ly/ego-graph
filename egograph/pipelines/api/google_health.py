"""Google Health OAuth and connection API."""

from fastapi import APIRouter, Depends, HTTPException, Query

from pipelines.api.dependencies import get_service, verify_api_key
from pipelines.service import PipelineService
from pipelines.sources.google_health.client import GoogleHealthAPIError
from pipelines.sources.google_health.data_types import SMOKE_TEST_DATA_TYPES

router = APIRouter(
    prefix="/v1/sources/google-health",
    tags=["sources", "google_health"],
)


def _require_auth(service: PipelineService):
    if service.google_health_auth is None:
        raise HTTPException(
            status_code=503,
            detail="invalid_google_health_config: OAuth settings are incomplete",
        )
    return service.google_health_auth


def _require_client(service: PipelineService):
    if service.google_health_client is None:
        raise HTTPException(
            status_code=503,
            detail="invalid_google_health_config: OAuth settings are incomplete",
        )
    return service.google_health_client


@router.get("/auth/start")
def start_authorization(
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> dict[str, str]:
    """Google OAuth 認可 URL を生成する。"""
    auth = _require_auth(service)
    return {"authorization_url": auth.start_authorization()}


@router.get("/auth/callback")
def complete_authorization(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    service: PipelineService = Depends(get_service),
) -> dict:
    """Google OAuth callback を処理する。"""
    auth = _require_auth(service)
    try:
        connection = auth.complete_authorization(code=code, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "connection_id": connection.connection_id,
        "status": connection.status,
        "scopes": connection.scopes,
    }


@router.get("/connection")
def get_connection(
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> dict:
    """Google Health connection 状態を取得する。"""
    connection = service.google_health_repository.get_connection()
    if connection is None:
        return {"connected": False, "status": None}
    return {
        "connected": True,
        "connection_id": connection.connection_id,
        "status": connection.status,
        "scopes": connection.scopes,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
        "last_error_message": connection.last_error_message,
    }


@router.delete("/connection", status_code=204)
def delete_connection(
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> None:
    """Google Health connection と token を削除する。"""
    connection = service.google_health_repository.get_connection()
    if connection is not None:
        service.google_health_repository.delete_connection(connection.connection_id)


@router.post("/connection/smoke-test")
def smoke_test_connection(
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> dict:
    """代表 data type を呼び出して接続を確認する。"""
    connection = service.google_health_repository.get_connection()
    if connection is None:
        raise HTTPException(
            status_code=409,
            detail="invalid_google_health_connection: connection not found",
        )
    client = _require_client(service)
    try:
        results = {
            data_type: len(
                client.list_data_points(
                    connection.connection_id,
                    data_type,
                ).get("dataPoints", [])
            )
            for data_type in SMOKE_TEST_DATA_TYPES
        }
    except GoogleHealthAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok", "data_types": results}
