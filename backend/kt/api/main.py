"""FastAPI application: REST API v1 + optional static web UI."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kt import __version__
from kt.access.service import NotFound
from kt.api.routes import admin, knowledge, topology
from kt.config import get_settings
from kt.db.session import init_db

log = logging.getLogger("kt.api")


def _error(status: int, code: str, message: str, trace_id: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "trace_id": trace_id}}, status_code=status,
                        headers={"X-Trace-Id": trace_id})


def create_app() -> FastAPI:
    settings = get_settings()
    init_db()
    app = FastAPI(title="Knowledge Topology API", version=__version__,
                  description="Maps, measures and serves organisational knowledge. All reads are ACL-filtered.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["X-Trace-Id"])

    @app.middleware("http")
    async def trace(request: Request, call_next):
        request.state.trace_id = request.headers.get("X-Trace-Id") or "trc_" + uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound):
        # Missing and forbidden are indistinguishable on purpose.
        return _error(404, "NOT_FOUND", "The requested resource is unavailable.", request.state.trace_id)

    @app.exception_handler(PermissionError)
    async def forbidden(request: Request, exc: PermissionError):
        return _error(403, "FORBIDDEN", str(exc), request.state.trace_id)

    @app.exception_handler(ValueError)
    async def bad_request(request: Request, exc: ValueError):
        return _error(400, "BAD_REQUEST", str(exc), request.state.trace_id)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
        return _error(exc.status_code, detail.get("code", "HTTP_ERROR"), detail.get("message", ""),
                      request.state.trace_id)

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError):
        return _error(422, "VALIDATION_ERROR", str(exc.errors()[:3]), request.state.trace_id)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(knowledge.router)
    app.include_router(topology.router)
    app.include_router(admin.router)

    dist = settings.web_dist_dir
    if dist and Path(dist).is_dir():
        app.mount("/assets", StaticFiles(directory=Path(dist) / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            target = Path(dist) / path
            if path and target.is_file():
                return FileResponse(target)
            return FileResponse(Path(dist) / "index.html")

    return app


# Run with: uvicorn --factory kt.api.main:create_app
