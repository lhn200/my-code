"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.health import router as health_router
from .api.resumes import router as resumes_router
from .api.runs import router as runs_router
from .checkpoint.sqlite import open_checkpointer
from .config import Settings
from .db import init_db
from .errors import ApiError, field_error, internal_error, validation_fields
from .graph.main import build_main_graph
from .runtime import create_context

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, model_factory=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.schema = init_db(settings.checkpoint_db_path)
        context = create_context(settings, model_factory=model_factory)
        app.state.context = context
        async with open_checkpointer(settings.checkpoint_db_path) as saver:
            app.state.graph = build_main_graph(context, checkpointer=saver)
            yield

    app = FastAPI(title="Career Assistant API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(runs_router, prefix=settings.api_prefix)
    app.include_router(resumes_router, prefix=settings.api_prefix)

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = validation_fields(exc.errors())
        if request.method == "POST" and request.url.path.rstrip("/").endswith("/runs"):
            try:
                raw = await request.body()
                body = json.loads(raw or b"{}")
            except Exception:
                body = {}
            jobs = body.get("jobs") if isinstance(body, dict) else None
            if isinstance(jobs, list) and len(jobs) > settings.max_jobs:
                fields.append(
                    field_error(
                        "jobs",
                        "too_many_jobs",
                        f"at most {settings.max_jobs} jobs per run",
                    )
                )
        fields.sort(key=lambda item: (item["field"], item["type"]))
        code = (
            "too_many_jobs"
            if fields and all(item["type"] == "too_many_jobs" for item in fields)
            else "validation_error"
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": code,
                    "message": "request validation failed",
                    "fields": fields,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=internal_error().payload())

    return app


app = create_app()
