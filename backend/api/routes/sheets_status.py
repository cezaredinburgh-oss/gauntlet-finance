"""Sheets connection status (for setup verification)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.api.deps import RepoDep, SettingsDep, UserDep, clear_repo_cache
from backend.schema.models import SHEET_HEADERS, InvestmentLot, LotStatus
from backend.services.response_cache import cache_invalidate
from backend.sheets.google_sheets import (
    GoogleSheetsRepository,
    service_account_email,
)
from backend.sheets.repository import InMemorySheetsRepository

router = APIRouter(tags=["sheets"])


@router.get("/sheets/status")
async def sheets_status(
    repo: RepoDep,
    settings: SettingsDep,
    user: UserDep,
) -> dict[str, Any]:
    """
    Verify repository backend and list tabs.

    Use after setup to confirm the real Google Sheet is connected.
    Multi-tenant: reports the bound tenant spreadsheet id, not env SPREADSHEET_ID.
    """
    bound_id = getattr(repo, "spreadsheet_id", None) or (
        user.spreadsheet_id if settings.multi_tenant else settings.spreadsheet_id
    )

    if isinstance(repo, InMemorySheetsRepository):
        msg = (
            "Multi-tenant memory ledger for this account."
            if settings.multi_tenant
            else (
                "In-memory store active (no SPREADSHEET_ID). "
                "Set SPREADSHEET_ID + service account to use Google Sheets."
            )
        )
        return {
            "backend": "memory",
            "spreadsheet_id": bound_id if settings.multi_tenant else None,
            "multi_tenant": settings.multi_tenant,
            "message": msg,
            "required_tabs": list(SHEET_HEADERS.keys()),
            "tabs": list(SHEET_HEADERS.keys()),
            "missing_tabs": [],
            "ok": True,
        }

    if not isinstance(repo, GoogleSheetsRepository):
        return {
            "backend": type(repo).__name__,
            "spreadsheet_id": bound_id or settings.spreadsheet_id or None,
            "multi_tenant": settings.multi_tenant,
            "tabs": [],
            "message": "Unknown repository type",
        }

    try:
        tabs = repo.list_tab_names()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Cannot list tabs: {exc}") from exc

    missing = [t for t in SHEET_HEADERS if t not in tabs]
    sa_email = None
    try:
        sa_email = service_account_email(
            json_path=settings.google_application_credentials or None,
            json_inline=settings.google_service_account_json or None,
        )
    except Exception:  # noqa: BLE001
        sa_email = None

    return {
        "backend": "google_sheets",
        "spreadsheet_id": bound_id or settings.spreadsheet_id,
        "multi_tenant": settings.multi_tenant,
        "service_account_email": sa_email,
        "tabs": tabs,
        "required_tabs": list(SHEET_HEADERS.keys()),
        "missing_tabs": missing,
        "ok": len(missing) == 0,
        "message": "OK" if not missing else f"Missing tabs: {missing}",
    }


@router.post("/sheets/reload")
async def sheets_reload(
    repo: RepoDep,
    _user: UserDep,
) -> dict[str, Any]:
    """
    Drop in-process Sheets tab cache + response caches, then re-read lots.

    Use after external imports/scripts so the API sees the latest Google Sheet.
    """
    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    # Drop process-level repo singleton so the next request rebuilds cleanly
    clear_repo_cache()
    cache_invalidate()

    # Re-bind: invalidate on this instance, then count from a forced re-load
    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    lots = [r for r in repo.list_rows("InvestmentLots") if isinstance(r, InvestmentLot)]
    open_lots = [
        l
        for l in lots
        if l.status == LotStatus.OPEN
        and l.quantity_remaining > 0
        and not l.archived
    ]
    by_source: dict[str, int] = {}
    for l in open_lots:
        key = l.source or ""
        by_source[key] = by_source.get(key, 0) + 1

    return {
        "ok": True,
        "message": "Caches cleared; InvestmentLots reloaded from Google Sheets",
        "lots_total": len(lots),
        "lots_open": len(open_lots),
        "open_by_source": by_source,
    }
