"""Health endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """ヘルスチェック。"""
    return {"status": "ok"}
