"""Google Health OAuth、connection、ingest API。"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, model_validator

from pipelines.api.dependencies import get_service, verify_api_key
from pipelines.service import PipelineService
from pipelines.sources.google_health.client import GoogleHealthAPIError
from pipelines.sources.google_health.data_types import (
    INGEST_DATA_TYPE_BY_NAME,
    SMOKE_TEST_DATA_TYPES,
)
from pipelines.sources.google_health.models import GoogleHealthRunMode

router = APIRouter(
    prefix="/v1/sources/google-health",
    tags=["sources", "google_health"],
)


class GoogleHealthRunRequest(BaseModel):
    """Google Health取り込みrun作成リクエスト。"""

    mode: GoogleHealthRunMode
    date_from: date | None = Field(None, alias="from")
    date_to: date | None = Field(None, alias="to")
    data_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> "GoogleHealthRunRequest":
        unknown = set(self.data_types) - INGEST_DATA_TYPE_BY_NAME.keys()
        if unknown:
            raise ValueError(
                f"invalid_data_types: unsupported values: {', '.join(sorted(unknown))}"
            )
        if self.mode is GoogleHealthRunMode.INITIAL_BACKFILL:
            if self.date_from is not None or self.date_to is not None:
                raise ValueError(
                    "invalid_range: initial_backfill does not accept from/to"
                )
            if self.data_types:
                raise ValueError(
                    "invalid_data_types: initial_backfill targets all data types"
                )
            return self
        if self.date_from is None or self.date_to is None:
            raise ValueError("invalid_range: from and to are required")
        if self.date_from >= self.date_to:
            raise ValueError("invalid_range: from must be earlier than to")
        if self.mode is GoogleHealthRunMode.DATA_TYPE_RANGE and not self.data_types:
            raise ValueError("invalid_data_types: data_type_range requires data_types")
        if self.mode is GoogleHealthRunMode.RANGE and self.data_types:
            raise ValueError("invalid_data_types: range targets all data types")
        return self

    def to_run_input(
        self,
        *,
        timezone: ZoneInfo,
        now: datetime | None = None,
    ) -> dict:
        """実行時に解決済みのclosed-open期間へ変換する。"""
        if self.mode is GoogleHealthRunMode.INITIAL_BACKFILL:
            current = now or datetime.now(tz=timezone)
            date_to = current.astimezone(timezone).date() + timedelta(days=1)
            date_from = date_to - timedelta(days=90)
        else:
            date_from = self.date_from
            date_to = self.date_to
        if date_from is None or date_to is None:  # pragma: no cover
            raise ValueError("invalid_range: unresolved range")
        return {
            "mode": self.mode.value,
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "data_types": self.data_types,
        }


def _format_invalid_detail(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "request"
            reason = str(error["msg"])
            marker = "invalid_"
            if marker in reason and ":" in reason:
                details.append(reason[reason.index(marker) :])
            else:
                details.append(f"invalid_{field}: {reason}")
        return "; ".join(details)

    message = str(getattr(exc, "message", None) or exc).strip()
    if message.startswith("invalid_") and ":" in message:
        return message

    field = str(getattr(exc, "field", None) or "request").strip()
    reason = message.splitlines()[0] if message else exc.__class__.__name__
    return f"invalid_{field}: {reason}"


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
        raise HTTPException(
            status_code=400,
            detail=_format_invalid_detail(exc),
        ) from exc
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
        raise HTTPException(
            status_code=502,
            detail=_format_invalid_detail(exc),
        ) from exc
    return {"status": "ok", "data_types": results}


@router.post("/runs", status_code=201)
def create_ingest_run(
    request_body: dict = Body(...),
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> dict:
    """Google Health取り込みrunを作成する。"""
    try:
        request = GoogleHealthRunRequest.model_validate(request_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=_format_invalid_detail(exc),
        ) from exc
    connection = service.google_health_repository.get_connection()
    if connection is None or connection.status.value != "active":
        raise HTTPException(
            status_code=409,
            detail="invalid_google_health_connection: active connection not found",
        )
    _require_client(service)
    run = service.trigger_google_health_ingest(
        request.to_run_input(timezone=ZoneInfo(service.config.timezone))
    )
    return run.__dict__
