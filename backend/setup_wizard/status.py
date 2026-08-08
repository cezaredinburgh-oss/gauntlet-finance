"""Probe setup progress without requiring a fully wired repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.schema.models import SHEET_HEADERS
from backend.setup_wizard.env_file import default_credentials_path, env_path, project_root
from backend.sheets.google_sheets import (
    credentials_from_service_account,
    resolve_service_account_path,
    service_account_email,
)


def collect_setup_status() -> dict[str, Any]:
    """Return a step-oriented status snapshot for the wizard UI."""
    get_settings.cache_clear()
    settings = get_settings()

    creds_path = resolve_service_account_path(settings.google_application_credentials)
    default_path = default_credentials_path()
    has_creds_file = creds_path is not None and creds_path.is_file()
    has_inline = bool((settings.google_service_account_json or "").strip())

    sa_email: str | None = None
    creds_error: str | None = None
    try:
        if has_creds_file or has_inline:
            sa_email = service_account_email(
                json_path=str(creds_path) if creds_path else settings.google_application_credentials,
                json_inline=settings.google_service_account_json or None,
            )
    except Exception as exc:  # noqa: BLE001
        creds_error = str(exc)

    spreadsheet_id = (settings.spreadsheet_id or "").strip()
    has_sheet_id = bool(spreadsheet_id)

    connection: dict[str, Any] = {
        "ok": False,
        "error": None,
        "tabs": [],
        "missing_tabs": list(SHEET_HEADERS.keys()),
        "tab_status": {},
    }

    if (has_creds_file or has_inline) and has_sheet_id and not creds_error:
        try:
            from backend.sheets.google_sheets import GoogleSheetsRepository

            creds = credentials_from_service_account(
                json_path=str(creds_path) if creds_path else None,
                json_inline=settings.google_service_account_json or None,
            )
            repo = GoogleSheetsRepository(
                spreadsheet_id=spreadsheet_id,
                credentials=creds,
                ensure_tabs=False,
            )
            tabs = repo.list_tab_names()
            missing = [t for t in SHEET_HEADERS if t not in tabs]
            connection = {
                "ok": len(missing) == 0,
                "error": None,
                "tabs": tabs,
                "missing_tabs": missing,
                "connected": True,
            }
        except Exception as exc:  # noqa: BLE001
            connection = {
                "ok": False,
                "error": str(exc),
                "tabs": [],
                "missing_tabs": list(SHEET_HEADERS.keys()),
                "connected": False,
            }
    else:
        connection["connected"] = False
        if not (has_creds_file or has_inline):
            connection["error"] = "Service account key not found"
        elif not has_sheet_id:
            connection["error"] = "SPREADSHEET_ID not set"
        elif creds_error:
            connection["error"] = creds_error

    steps = {
        "cloud_project": {
            "id": 1,
            "title": "Google Cloud project & APIs",
            "done": None,  # manual checklist in UI
            "hint": "Create a project and enable Sheets + Drive APIs",
        },
        "service_account": {
            "id": 2,
            "title": "Service account key",
            "done": bool(sa_email),
            "path": str(creds_path) if creds_path else str(default_path),
            "email": sa_email,
            "error": creds_error,
        },
        "spreadsheet": {
            "id": 3,
            "title": "Spreadsheet ID",
            "done": has_sheet_id,
            "spreadsheet_id": spreadsheet_id or None,
        },
        "share": {
            "id": 4,
            "title": "Share sheet with service account",
            "done": connection.get("connected") is True,
            "service_account_email": sa_email,
            "hint": "Editor access required",
        },
        "tabs": {
            "id": 5,
            "title": "Create tabs & headers",
            "done": connection.get("ok") is True,
            "missing_tabs": connection.get("missing_tabs") or [],
        },
    }

    # Overall progress: steps 2–5 automated; step 1 is manual
    auto_done = sum(
        1
        for k in ("service_account", "spreadsheet", "share", "tabs")
        if steps[k]["done"]
    )

    return {
        "project_root": str(project_root()),
        "env_file": str(env_path()),
        "env_exists": env_path().is_file(),
        "auth_mode": settings.auth_mode,
        "wizard_enabled": True,
        "service_account_email": sa_email,
        "credentials_path": str(creds_path) if creds_path else str(default_path),
        "credentials_found": has_creds_file or has_inline,
        "spreadsheet_id": spreadsheet_id or None,
        "connection": connection,
        "required_tabs": list(SHEET_HEADERS.keys()),
        "steps": steps,
        "progress": {
            "auto_steps_done": auto_done,
            "auto_steps_total": 4,
            "percent": int(auto_done / 4 * 100),
            "ready": connection.get("ok") is True,
        },
        "links": {
            "cloud_console": "https://console.cloud.google.com/",
            "create_project": "https://console.cloud.google.com/projectcreate",
            "api_library": "https://console.cloud.google.com/apis/library",
            "sheets_api": "https://console.cloud.google.com/apis/library/sheets.googleapis.com",
            "drive_api": "https://console.cloud.google.com/apis/library/drive.googleapis.com",
            "credentials": "https://console.cloud.google.com/apis/credentials",
            "new_sheet": "https://sheets.google.com/create",
            "docs": "/docs",
            "health": "/health",
        },
    }
