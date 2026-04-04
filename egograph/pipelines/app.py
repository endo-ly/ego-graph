"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from pipelines.api import browser_history, health, runs, workflows
from pipelines.config import PipelinesConfig
from pipelines.service import PipelineService


def create_app(config: PipelinesConfig | None = None) -> FastAPI:
    """pipelines FastAPI app を組み立てる。"""
    service = PipelineService.create(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service
        service.start()
        try:
            yield
        finally:
            service.stop()

    app = FastAPI(
        title="EgoGraph Pipelines Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.service = service
    app.include_router(health.router)
    app.include_router(workflows.router)
    app.include_router(runs.router)
    app.include_router(browser_history.router)
    return app
