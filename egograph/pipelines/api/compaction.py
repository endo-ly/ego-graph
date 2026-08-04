"""Dataset catalog と manual compaction run のAPI。"""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from pipelines.api.dependencies import get_service, verify_api_key
from pipelines.compaction import DatasetCompactionTarget
from pipelines.domain.errors import PipelinesError
from pipelines.service import PipelineService

router = APIRouter(prefix="/v1", tags=["datasets", "compaction"])


class CompactionTargetRequest(BaseModel):
    """月次 compaction の対象指定。"""

    dataset_id: str = Field(min_length=1)
    year: int = Field(strict=True, ge=1, le=9999)
    month: int = Field(strict=True, ge=1, le=12)

    def to_target(self) -> DatasetCompactionTarget:
        """domain の compaction target へ変換する。"""
        return DatasetCompactionTarget(
            dataset_id=self.dataset_id,
            year=self.year,
            month=self.month,
        )


class CompactionRunRequest(BaseModel):
    """manual compaction run 作成リクエスト。"""

    targets: list[CompactionTargetRequest] = Field(min_length=1)

    def to_targets(self) -> tuple[DatasetCompactionTarget, ...]:
        """domain の compaction target 列へ変換する。"""
        return tuple(target.to_target() for target in self.targets)


def _format_invalid_detail(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "request"
            details.append(f"invalid_{field}: {error['msg']}")
        return "; ".join(details)

    message = str(exc).strip()
    if message.startswith("invalid_") and ":" in message:
        return message
    return f"invalid_request: {message or exc.__class__.__name__}"


@router.get("/datasets")
def list_datasets(
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> list[dict]:
    """dataset catalog の一覧を取得する。"""
    return service.list_datasets()


@router.post("/compaction/runs", status_code=201)
def create_compaction_run(
    request_body: Any = Body(...),
    _: None = Depends(verify_api_key),
    service: PipelineService = Depends(get_service),
) -> dict:
    """指定 dataset partition の manual compaction run をqueueへ積む。"""
    try:
        request = CompactionRunRequest.model_validate(request_body)
        run = service.trigger_compaction(request.to_targets())
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=_format_invalid_detail(exc),
        ) from exc
    except (PipelinesError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=_format_invalid_detail(exc),
        ) from exc
    return run.__dict__
