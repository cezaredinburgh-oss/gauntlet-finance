"""
Gauntlet Finance FastAPI application.

Run:
  uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8020

Domain API lives under ``/api/*``. UI (production) is served from the same origin;
SPA deep links are not under ``/api``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import (
    admin,
    auth_routes,
    categories,
    dashboard,
    exports as exports_routes,
    fx as fx_routes,
    investments,
    invites,
    prices,
    setup_wizard,
    sheets_status,
    tax,
    tenant,
    transactions,
    upload,
)
from backend.api.schemas import HealthResponse
from backend.config import get_settings

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"


def _health_payload() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok",
        app=s.app_name,
        auth_mode=s.auth_mode,
        spreadsheet_configured=s.spreadsheet_configured,
    )


def _safe_dist_file(dist_root: Path, path: str) -> Path | None:
    """
    Resolve a static file under dist_root only if ``path`` stays inside the tree.

    Prevents path traversal (e.g. ``../.env``) via SPA fallback.
    """
    if not path:
        return None
    root = dist_root.resolve()
    candidate = (root / path).resolve()
    try:
        ok = candidate.is_relative_to(root)
    except AttributeError:  # pragma: no cover — Python < 3.9
        ok = str(candidate).startswith(str(root))
    if ok and candidate.is_file():
        return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if settings.require_sheets and not settings.spreadsheet_configured:
        logger.error(
            "REQUIRE_SHEETS=true but SPREADSHEET_ID is empty. "
            "Set SPREADSHEET_ID + GOOGLE_SERVICE_ACCOUNT_JSON in host variables. "
            "App is starting in degraded mode so deploys can succeed."
        )
    if (
        settings.is_production
        and settings.auth_mode in {"dev", "disabled"}
        and not settings.allow_open_auth
    ):
        logger.critical(
            "Production with AUTH_MODE=%s and ALLOW_OPEN_AUTH=false: "
            "API will refuse open access (503). Set AUTH_MODE=oauth or "
            "ALLOW_OPEN_AUTH=true for trusted single-user deploys only.",
            settings.auth_mode,
        )
    logger.info(
        "Starting %s (auth_mode=%s, spreadsheet=%s, multi_tenant=%s)",
        settings.app_name,
        settings.auth_mode,
        settings.spreadsheet_configured,
        settings.multi_tenant,
    )
    if settings.multi_tenant:
        # Ensure control DB + platform admins exist at boot
        from backend.tenancy.store import get_control_store

        get_control_store(settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Personal finance backend: Google Sheets storage, statement parsers, "
            "FIFO lots, internal-transfer matching, yfinance prices, tax JSON report.\n\n"
            "Domain API: `/api/*` · Setup wizard: `/setup` · Docs: `/docs` · "
            "Health: `/health` and `/api/health`."
        ),
        lifespan=lifespan,
    )

    # Never fall back to CORS * in production (empty list = no browser cross-origin).
    cors_origins = settings.cors_origin_list
    if not cors_origins:
        cors_origins = [] if settings.is_production else ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
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

    # Railway / process health (root) + consistent /api health for the SPA
    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_root() -> HealthResponse:
        return _health_payload()

    api = APIRouter(prefix="/api")

    @api.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_api() -> HealthResponse:
        return _health_payload()

    api.include_router(auth_routes.router)
    api.include_router(sheets_status.router)
    api.include_router(upload.router)
    api.include_router(transactions.router)
    api.include_router(investments.router)
    api.include_router(categories.router)
    api.include_router(dashboard.router)
    api.include_router(prices.router)
    api.include_router(tax.router)
    api.include_router(exports_routes.router)
    api.include_router(admin.router)
    api.include_router(invites.router)
    api.include_router(tenant.router)
    api.include_router(fx_routes.router)

    app.include_router(api)

    # First-time setup wizard stays at /setup (HTML + /setup/api/* JSON)
    app.include_router(setup_wizard.router)

    serve_spa = (
        settings.app_env == "production"
        and _FRONTEND_DIST.is_dir()
        and (_FRONTEND_DIST / "index.html").is_file()
    )

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        s = get_settings()
        if serve_spa:
            return FileResponse(_FRONTEND_DIST / "index.html")
        if not s.spreadsheet_configured:
            return RedirectResponse(url="/setup", status_code=302)
        return RedirectResponse(url="/docs", status_code=302)

    if serve_spa:
        assets = _FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            """
            Serve static files from the React build, else index.html for UI routes.

            Domain APIs live only under /api/* (registered above). Never serve
            the SPA for /api, /docs, /setup, or /health.
            """
            path = (full_path or "").strip("/")
            head = path.split("/", 1)[0] if path else ""

            # Never hijack API / docs / setup / health
            if head in {
                "api",
                "docs",
                "redoc",
                "openapi.json",
                "health",
                "setup",
            }:
                return JSONResponse({"detail": "Not Found"}, status_code=404)

            if path:
                safe = _safe_dist_file(_FRONTEND_DIST, path)
                if safe is not None:
                    return FileResponse(safe)

            return FileResponse(_FRONTEND_DIST / "index.html")

        logger.info("Serving frontend SPA from %s", _FRONTEND_DIST)

    return app


app = create_app()
