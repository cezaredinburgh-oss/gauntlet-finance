"""
Gauntlet Finance FastAPI application.

Run:
  uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8020
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import (
    admin,
    auth_routes,
    categories,
    dashboard,
    investments,
    prices,
    setup_wizard,
    sheets_status,
    tax,
    transactions,
    upload,
)
from backend.api.schemas import HealthResponse
from backend.config import get_settings

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if settings.require_sheets and not settings.spreadsheet_configured:
        # Do not crash the process — Railway would restart forever (deploy loop).
        # Health still returns ok; spreadsheet_configured stays false until env is set.
        logger.error(
            "REQUIRE_SHEETS=true but SPREADSHEET_ID is empty. "
            "Set SPREADSHEET_ID + GOOGLE_SERVICE_ACCOUNT_JSON in host variables. "
            "App is starting in degraded mode so deploys can succeed."
        )
    logger.info(
        "Starting %s (auth_mode=%s, spreadsheet=%s)",
        settings.app_name,
        settings.auth_mode,
        settings.spreadsheet_configured,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Personal finance backend: Google Sheets storage, statement parsers, "
            "FIFO lots, internal-transfer matching, yfinance prices, tax JSON report.\n\n"
            "Setup wizard: `/setup` · API docs: `/docs` · Health: `/health`."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc) if settings.debug else "Internal server error"},
        )

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        s = get_settings()
        return HealthResponse(
            status="ok",
            app=s.app_name,
            auth_mode=s.auth_mode,
            spreadsheet_configured=s.spreadsheet_configured,
        )

    app.include_router(auth_routes.router)
    app.include_router(setup_wizard.router)
    app.include_router(sheets_status.router)
    app.include_router(upload.router)
    app.include_router(transactions.router)
    app.include_router(investments.router)
    app.include_router(categories.router)
    app.include_router(dashboard.router)
    app.include_router(prices.router)
    app.include_router(tax.router)
    app.include_router(admin.router)

    serve_spa = (
        settings.app_env == "production"
        and _FRONTEND_DIST.is_dir()
        and (_FRONTEND_DIST / "index.html").is_file()
    )

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        s = get_settings()
        if serve_spa:
            from fastapi.responses import FileResponse

            return FileResponse(_FRONTEND_DIST / "index.html")
        if not s.spreadsheet_configured:
            return RedirectResponse(url="/setup", status_code=302)
        return RedirectResponse(url="/docs", status_code=302)

    # Single-service deploy: serve React build from FastAPI (production only)
    if serve_spa:
        assets = _FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # API routers are registered first and take precedence for known paths
            reserved = (
                "api", "docs", "redoc", "openapi.json", "health", "setup",
                "auth", "upload", "transactions", "investments", "categories",
                "dashboard", "prices", "tax", "admin", "sheets", "alerts",
            )
            head = (full_path or "").split("/", 1)[0]
            if head in reserved:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                from fastapi.responses import FileResponse

                return FileResponse(candidate)
            from fastapi.responses import FileResponse

            return FileResponse(_FRONTEND_DIST / "index.html")

        logger.info("Serving frontend SPA from %s", _FRONTEND_DIST)

    return app


app = create_app()
