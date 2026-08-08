"""Interactive Google Sheets setup wizard (HTML + JSON API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from backend.api.deps import clear_repo_cache
from backend.config import get_settings
from backend.schema.models import SHEET_HEADERS
from backend.setup_wizard.env_file import (
    default_credentials_path,
    extract_spreadsheet_id,
    project_root,
    secrets_dir,
    upsert_env_vars,
)
from backend.setup_wizard.status import collect_setup_status
from backend.sheets.google_sheets import (
    GoogleSheetsRepository,
    create_spreadsheet,
    credentials_from_service_account,
    service_account_email,
)

router = APIRouter(tags=["setup-wizard"])

_WIZARD_HTML = Path(__file__).resolve().parents[2] / "setup_wizard" / "static" / "wizard.html"


def _wizard_allowed() -> None:
    settings = get_settings()
    # Allow in development / debug; block pure production unless explicitly enabled
    if settings.app_env == "production" and not settings.debug:
        # still allow if no sheet configured (first-time setup)
        if settings.spreadsheet_id:
            raise HTTPException(
                status_code=403,
                detail="Setup wizard disabled in production when a sheet is already configured.",
            )


def _reload_settings() -> None:
    get_settings.cache_clear()
    clear_repo_cache()
    # Reset in-memory repo so next request rebuilds with new env
    import backend.api.deps as deps

    deps._DEV_MEMORY_REPO = None


class SpreadsheetBody(BaseModel):
    spreadsheet_id: str = Field(..., min_length=5)


class EnsureTabsBody(BaseModel):
    seed: bool = False


class CreateSpreadsheetBody(BaseModel):
    title: str = Field(default="Gauntlet Finance Data", min_length=1, max_length=200)
    # Optional: your personal Gmail so you can open the SA-owned sheet in browser
    share_with_email: str = ""


class DeploySecretsBody(BaseModel):
    public_url: str = Field(
        default="",
        description="Deployed HTTPS origin, e.g. https://gauntlet.up.railway.app",
    )


@router.get("/setup", response_class=HTMLResponse, include_in_schema=False)
async def setup_wizard_page() -> HTMLResponse:
    """Browser UI for Google Sheets setup."""
    _wizard_allowed()
    if not _WIZARD_HTML.is_file():
        raise HTTPException(status_code=500, detail=f"Wizard HTML missing: {_WIZARD_HTML}")
    return HTMLResponse(_WIZARD_HTML.read_text(encoding="utf-8"))


@router.get("/setup/api/status")
async def setup_status() -> dict[str, Any]:
    _wizard_allowed()
    return collect_setup_status()


@router.post("/setup/api/upload-credentials")
async def upload_credentials(file: UploadFile = File(...)) -> dict[str, Any]:
    """Save service-account JSON to secrets/service-account.json and update .env."""
    _wizard_allowed()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        info = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    if "client_email" not in info or "private_key" not in info:
        raise HTTPException(
            status_code=400,
            detail="This does not look like a Google service-account key "
            "(need client_email and private_key).",
        )

    dest = default_credentials_path()
    secrets_dir()
    dest.write_text(json.dumps(info, indent=2), encoding="utf-8")

    # Relative path from project root for .env portability
    try:
        rel = dest.relative_to(project_root()).as_posix()
    except ValueError:
        rel = str(dest)

    upsert_env_vars(
        {
            "AUTH_MODE": "dev",
            "GOOGLE_APPLICATION_CREDENTIALS": rel,
        }
    )
    _reload_settings()

    email = info.get("client_email", "")
    return {
        "ok": True,
        "path": rel,
        "client_email": email,
        "message": f"Saved key. Share your spreadsheet with {email} as Editor.",
    }


@router.post("/setup/api/save-spreadsheet")
async def save_spreadsheet(body: SpreadsheetBody) -> dict[str, Any]:
    _wizard_allowed()
    sid = extract_spreadsheet_id(body.spreadsheet_id)
    if len(sid) < 10:
        raise HTTPException(
            status_code=400,
            detail="Spreadsheet ID looks too short. Paste the full Google Sheets URL.",
        )
    upsert_env_vars(
        {
            "AUTH_MODE": "dev",
            "SPREADSHEET_ID": sid,
            "GOOGLE_APPLICATION_CREDENTIALS": (
                get_settings().google_application_credentials
                or "secrets/service-account.json"
            ),
        }
    )
    _reload_settings()
    return {"ok": True, "spreadsheet_id": sid, "message": "SPREADSHEET_ID saved to .env"}


@router.post("/setup/api/create-spreadsheet")
async def create_spreadsheet_route(body: CreateSpreadsheetBody | None = None) -> dict[str, Any]:
    """
    Create a new Google Spreadsheet with the service account (Drive/Sheets API).

    Prefer this over manual create+share: the SA owns the file; optionally share
    with your human Gmail so you can open it in the browser.
    """
    _wizard_allowed()
    body = body or CreateSpreadsheetBody()
    _reload_settings()
    settings = get_settings()
    try:
        creds = credentials_from_service_account(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Service account key required first: {exc}",
        ) from exc

    try:
        result = create_spreadsheet(
            creds,
            title=(body.title or "Gauntlet Finance Data").strip(),
            share_with_email=(body.share_with_email or "").strip() or None,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not create spreadsheet: {exc}. "
                "Enable Google Sheets API + Drive API and use a valid service-account key."
            ),
        ) from exc

    sid = result["spreadsheet_id"]
    upsert_env_vars(
        {
            "AUTH_MODE": "dev",
            "SPREADSHEET_ID": sid,
            "GOOGLE_APPLICATION_CREDENTIALS": (
                settings.google_application_credentials
                or "secrets/service-account.json"
            ),
        }
    )
    _reload_settings()

    # Prepare tabs immediately
    tabs_msg = ""
    try:
        repo = GoogleSheetsRepository(
            spreadsheet_id=sid,
            credentials=creds,
            ensure_tabs=False,
        )
        repo.ensure_all_tabs()
        try:
            from backend.schema.ensure_defaults import (
                ensure_default_categories,
                ensure_digital_assets_rule,
            )

            ensure_default_categories(repo)
            ensure_digital_assets_rule(repo)
            tabs_msg = " Tabs, categories, and Digital Assets rule ready."
        except Exception as exc:  # noqa: BLE001
            tabs_msg = f" Tabs created; seed note: {exc}"
    except Exception as exc:  # noqa: BLE001
        tabs_msg = f" Sheet created but tab setup failed: {exc}"

    return {
        "ok": True,
        "spreadsheet_id": sid,
        "url": result.get("url"),
        "shared_with": result.get("shared_with") or "",
        "share_warning": result.get("share_warning") or "",
        "message": (
            f"Created spreadsheet and saved SPREADSHEET_ID.{tabs_msg}"
            + (
                f" Shared with {result.get('shared_with')}."
                if result.get("shared_with")
                else " Optionally share with your Gmail to open in browser."
            )
        ),
    }


@router.post("/setup/api/prepare-ledger")
async def prepare_ledger() -> dict[str, Any]:
    """Ensure tabs + default categories + Digital Assets seed rule."""
    _wizard_allowed()
    _reload_settings()
    settings = get_settings()
    if not settings.spreadsheet_id:
        raise HTTPException(status_code=400, detail="SPREADSHEET_ID not set")

    try:
        creds = credentials_from_service_account(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        )
        repo = GoogleSheetsRepository(
            spreadsheet_id=settings.spreadsheet_id,
            credentials=creds,
            ensure_tabs=False,
        )
        tab_status = repo.ensure_all_tabs()
        from backend.schema.ensure_defaults import (
            ensure_default_categories,
            ensure_digital_assets_rule,
        )

        n_cats = ensure_default_categories(repo)
        da = ensure_digital_assets_rule(repo)
        try:
            from backend.scripts.seed_dev_repo import seed_minimal

            seed_minimal(repo)
            seed_note = "Seed accounts applied if empty."
        except Exception as exc:  # noqa: BLE001
            seed_note = f"Seed accounts skipped: {exc}"

        tabs = repo.list_tab_names()
        missing = [t for t in SHEET_HEADERS if t not in tabs]
        return {
            "ok": len(missing) == 0,
            "message": (
                f"Ledger prepared. Categories written: {n_cats}. "
                f"Digital Assets rule updated: {bool(da)}. {seed_note}"
            ),
            "tab_status": tab_status,
            "tabs": tabs,
            "missing_tabs": missing,
            "categories_written": n_cats,
            "digital_assets_rule": da,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/setup/api/deploy-env")
async def deploy_env_preview(public_url: str = "") -> dict[str, Any]:
    """
    Build Railway/Render environment variables from local config (for copy-paste).

    Does not write secrets to disk. JSON key is returned only if present locally.
    """
    _wizard_allowed()
    _reload_settings()
    settings = get_settings()
    import secrets as _secrets

    origin = (public_url or "").strip().rstrip("/")
    sa_json = ""
    path = settings.google_application_credentials or "secrets/service-account.json"
    try:
        from backend.sheets.google_sheets import resolve_service_account_path

        p = resolve_service_account_path(path)
        if p and p.is_file():
            sa_json = p.read_text(encoding="utf-8").replace("\n", "").replace("\r", "")
    except Exception:  # noqa: BLE001
        sa_json = ""
    if settings.google_service_account_json:
        sa_json = settings.google_service_account_json.replace("\n", "").replace("\r", "")

    secret = settings.secret_key
    if not secret or secret.startswith("dev-change") or secret.startswith("change-me"):
        secret = _secrets.token_urlsafe(32)

    env = {
        "APP_ENV": "production",
        "DEBUG": "false",
        "AUTH_MODE": "dev",
        "REQUIRE_SHEETS": "true",
        "SPREADSHEET_ID": settings.spreadsheet_id or "",
        "SECRET_KEY": secret,
        "SESSION_COOKIE_NAME": settings.session_cookie_name or "gf_session",
        "CORS_ORIGINS": origin or "https://YOUR-APP.up.railway.app",
        "PRIMARY_DISPLAY_CURRENCY": settings.primary_display_currency or "USD",
        "SECONDARY_DISPLAY_CURRENCY": settings.secondary_display_currency or "CZK",
        "HOLDING_PERIOD_EXEMPTION_DAYS": str(
            settings.holding_period_exemption_days or 1095
        ),
    }
    if sa_json:
        env["GOOGLE_SERVICE_ACCOUNT_JSON"] = sa_json

    lines = [f"{k}={v}" for k, v in env.items()]
    return {
        "ok": bool(settings.spreadsheet_id and sa_json),
        "message": (
            "Copy these into Railway → Variables (or Render → Environment). "
            "Never commit them to GitHub."
            if settings.spreadsheet_id and sa_json
            else "Complete service account + spreadsheet steps first."
        ),
        "env": env,
        "env_file_text": "\n".join(lines) + "\n",
        "checklist": [
            "Create empty GitHub repo (do not upload secrets)",
            "Push code with scripts/Prepare-GitHub.ps1 or git push",
            "Railway: New Project → Deploy from GitHub",
            "Paste Variables from this page",
            "Set public URL, rebuild if CORS must match final domain",
            "Open /health then / on the public HTTPS URL",
        ],
        "links": {
            "railway": "https://railway.app/new",
            "render": "https://dashboard.render.com/select-repo?type=web",
            "github_new": "https://github.com/new",
            "deploy_doc": "/docs",  # UI-relative; full guide in docs/DEPLOY.md
        },
    }


@router.post("/setup/api/test-connection")
async def test_connection() -> dict[str, Any]:
    _wizard_allowed()
    _reload_settings()
    st = collect_setup_status()
    conn = st.get("connection") or {}
    if conn.get("connected"):
        return {
            "ok": True,
            "message": "Connected. Service account can open the spreadsheet.",
            "tabs": conn.get("tabs") or [],
            "missing_tabs": conn.get("missing_tabs") or [],
        }
    err = conn.get("error") or "Connection failed"
    # Friendly hints
    hint = ""
    low = err.lower()
    if "permission" in low or "403" in low:
        hint = (
            " Share the sheet with the service account email as Editor "
            f"({st.get('service_account_email') or 'see step 2'})."
        )
    elif "not found" in low or "404" in low:
        hint = " Check SPREADSHEET_ID is correct."
    elif "api" in low and "enable" in low:
        hint = " Enable Google Sheets API in Cloud Console."
    return {
        "ok": False,
        "error": err,
        "message": err + hint,
        "service_account_email": st.get("service_account_email"),
    }


@router.post("/setup/api/ensure-tabs")
async def ensure_tabs(body: EnsureTabsBody | None = None) -> dict[str, Any]:
    _wizard_allowed()
    body = body or EnsureTabsBody()
    _reload_settings()
    settings = get_settings()
    if not settings.spreadsheet_id:
        raise HTTPException(status_code=400, detail="SPREADSHEET_ID not set — complete step 3")

    try:
        email = service_account_email(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        )
        creds = credentials_from_service_account(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        )
        repo = GoogleSheetsRepository(
            spreadsheet_id=settings.spreadsheet_id,
            credentials=creds,
            ensure_tabs=False,
        )
        tab_status = repo.ensure_all_tabs()
        tabs = repo.list_tab_names()
        missing = [t for t in SHEET_HEADERS if t not in tabs]

        seed_msg = ""
        if body.seed and not missing:
            try:
                from backend.scripts.seed_dev_repo import seed_minimal

                seed_minimal(repo)
                seed_msg = " Seed data applied if tables were empty."
            except Exception as exc:  # noqa: BLE001
                seed_msg = f" Seed warning: {exc}"

        _reload_settings()
        return {
            "ok": len(missing) == 0,
            "message": (
                "All tabs ready." + seed_msg
                if not missing
                else f"Still missing: {missing}"
            ),
            "tab_status": tab_status,
            "tabs": tabs,
            "missing_tabs": missing,
            "service_account_email": email,
            "required_tabs": list(SHEET_HEADERS.keys()),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
