"""Admin / maintenance endpoints (cleanup, warm cache, FX backfill, CNB, jobs)."""

from __future__ import annotations

import secrets
from datetime import date
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import (
    PlatformAdminDep,
    RepoDep,
    SettingsDep,
    UserDep,
    clear_repo_cache,
    open_tenant_repository,
)
from backend.services.cleanup import (
    CONFIRM_TOKEN,
    list_scopes,
    preview_cleanup,
    result_to_dict,
    run_cleanup,
)
from backend.services.jobs import (
    KIND_RUNNERS,
    get_job,
    list_jobs,
    start_known_job,
)
from backend.services.maintenance import (
    backfill_amount_usd,
    fetch_cnb_range,
    warm_cache,
)
from backend.services.response_cache import cache_invalidate
from backend.tenancy.context import reset_tenant_id, set_tenant_id
from backend.tenancy.store import get_control_store

router = APIRouter(prefix="/admin", tags=["admin"])


class CleanupRequest(BaseModel):
    scopes: list[str] = Field(..., min_length=1, description="Scope ids to clear")
    confirm: str = Field(
        ...,
        description=f'Must be exactly "{CONFIRM_TOKEN}" to proceed',
    )


@router.post("/migrate-env-sheet")
async def migrate_env_sheet(
    settings: SettingsDep,
    admin: PlatformAdminDep,
) -> dict[str, Any]:
    """
    One-shot: bind env SPREADSHEET_ID to the authenticated platform admin.

    Used when cutting over single-tenant → multi-tenant so the legacy ledger
    attaches without accidentally calling POST /tenant/provision (new empty sheet).

    Safe rules:
    - MULTI_TENANT required (PlatformAdminDep already 404s otherwise)
    - Env spreadsheet_id must be non-empty
    - Admin must not already have a *different* binding
    - Sheet must not be bound to another user (409)
    """
    from backend.tenancy.store import control_user_to_dict, get_control_store

    sheet_id = (settings.spreadsheet_id or "").strip()
    if not sheet_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "No SPREADSHEET_ID in environment. "
                "Set it or use POST /api/tenant/bind with an explicit spreadsheet_id."
            ),
        )
    if "/d/" in sheet_id:
        try:
            sheet_id = sheet_id.split("/d/")[1].split("/")[0]
        except IndexError:
            pass

    if not admin.user_id:
        raise HTTPException(status_code=403, detail="Account not registered.")

    store = get_control_store(settings)
    record = store.get_user_by_id(admin.user_id)
    if record is None:
        raise HTTPException(status_code=403, detail="Account not registered.")
    if record.disabled_at:
        raise HTTPException(status_code=403, detail="Account disabled.")

    existing = (record.spreadsheet_id or "").strip()
    if existing:
        if existing == sheet_id:
            return {
                "status": "already_bound",
                "spreadsheet_id": existing,
                "user": control_user_to_dict(record),
            }
        raise HTTPException(
            status_code=400,
            detail=(
                "Your account already has a different spreadsheet bound. "
                "Use POST /api/tenant/bind to reassign intentionally."
            ),
        )

    try:
        updated = store.claim_spreadsheet_id(
            admin.user_id, sheet_id, only_if_empty=True
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "already_provisioned":
            refreshed = store.get_user_by_id(admin.user_id)
            assert refreshed is not None
            if (refreshed.spreadsheet_id or "").strip() == sheet_id:
                return {
                    "status": "already_bound",
                    "spreadsheet_id": refreshed.spreadsheet_id,
                    "user": control_user_to_dict(refreshed),
                }
            raise HTTPException(
                status_code=400,
                detail="Your account already has a spreadsheet bound.",
            ) from exc
        if msg == "spreadsheet_already_bound":
            raise HTTPException(
                status_code=409,
                detail="That spreadsheet is already bound to another account.",
            ) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    clear_repo_cache(spreadsheet_id=sheet_id)
    return {
        "status": "bound",
        "spreadsheet_id": sheet_id,
        "user": control_user_to_dict(updated),
        "bound_by": admin.email,
        "source": "env_SPREADSHEET_ID",
    }


class JobStartBody(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    limit: int | None = Field(None, ge=1, le=50000)
    max_passes: int | None = Field(None, ge=1, le=20)


@router.get("/cleanup/preview")
async def cleanup_preview(repo: RepoDep, _user: UserDep) -> dict[str, Any]:
    """Row counts and scope descriptions for the Settings UI."""
    return preview_cleanup(repo)


@router.get("/cleanup/scopes")
async def cleanup_scopes(_user: UserDep) -> dict[str, Any]:
    return {"scopes": list_scopes(), "confirm_token": CONFIRM_TOKEN}


@router.post("/cleanup")
async def cleanup_run(
    body: CleanupRequest,
    repo: RepoDep,
    _user: UserDep,
) -> dict[str, Any]:
    if body.confirm != CONFIRM_TOKEN:
        raise HTTPException(
            status_code=400,
            detail=f'confirm must be exactly "{CONFIRM_TOKEN}"',
        )
    try:
        result = run_cleanup(repo, body.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if hasattr(repo, "invalidate_cache"):
        try:
            repo.invalidate_cache()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    sheet_id = getattr(repo, "spreadsheet_id", None)
    clear_repo_cache(spreadsheet_id=str(sheet_id) if sheet_id else None)
    cache_invalidate()

    return result_to_dict(result)


@router.post("/warm-cache")
async def warm_cache_endpoint(repo: RepoDep, _user: UserDep) -> dict[str, Any]:
    """Preload heavy Sheets tabs into process cache."""
    return warm_cache(repo)


@router.post("/backfill-fx")
async def backfill_fx_endpoint(
    repo: RepoDep,
    _user: UserDep,
    background: bool = Query(False),
    limit: int = Query(5000, ge=1, le=50000),
) -> dict[str, Any]:
    """Persist missing amount_usd / amount_czk on Transactions."""
    if not background:
        return backfill_amount_usd(repo, limit=limit)
    out = start_known_job(
        "fx-backfill-amounts", repo, params={"limit": limit, "max_passes": 1}
    )
    if out.get("status") == "rejected":
        raise HTTPException(status_code=409, detail=out.get("error"))
    return out


@router.post("/fetch-cnb")
async def fetch_cnb_endpoint(
    repo: RepoDep,
    _user: UserDep,
    date_from: date = Query(...),
    date_to: date = Query(...),
    background: bool = Query(False),
) -> dict[str, Any]:
    """Fetch CNB daily rates for a date range and upsert FXRates."""
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to must be >= date_from")
    if not background:
        if (date_to - date_from).days > 400:
            raise HTTPException(
                status_code=400,
                detail="range max 400 days for sync; use background=true or POST /admin/jobs/fx-fetch-cnb",
            )
        return fetch_cnb_range(repo, date_from=date_from, date_to=date_to)
    out = start_known_job(
        "fx-fetch-cnb",
        repo,
        params={
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    )
    if out.get("status") == "rejected":
        raise HTTPException(status_code=409, detail=out.get("error"))
    return out


@router.get("/jobs")
async def jobs_list(
    user: UserDep,
    settings: SettingsDep,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    tenant = user.user_id if settings.multi_tenant else None
    return {
        "items": list_jobs(limit=limit, tenant_id=tenant),
        "kinds": sorted(KIND_RUNNERS.keys()),
    }


@router.post("/jobs/tick")
async def jobs_tick(
    settings: SettingsDep,
    x_cron_secret: str | None = Header(default=None, alias="X-Cron-Secret"),
) -> dict[str, Any]:
    """
    Cron entrypoint: run fx-full when CRON_SECRET matches.

    Multi-tenant: fans out to every user with a bound spreadsheet (no user session).
    Single-tenant: runs against env SPREADSHEET_ID / memory backend.
    """
    expected = (settings.cron_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET not configured",
        )
    provided = (x_cron_secret or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid cron secret")

    if settings.multi_tenant:
        store = get_control_store(settings)
        started: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for u in store.list_users():
            if not u.spreadsheet_id or u.disabled_at:
                continue
            token = set_tenant_id(u.id)
            try:
                repo = open_tenant_repository(settings, u.spreadsheet_id)
                out = start_known_job(
                    "fx-full", repo, params={}, tenant_id=u.id
                )
            except Exception as exc:  # noqa: BLE001
                skipped.append(
                    {
                        "user_id": u.id,
                        "email": u.email,
                        "error": str(exc),
                    }
                )
                continue
            finally:
                reset_tenant_id(token)
            if out.get("status") == "rejected":
                skipped.append({**out, "user_id": u.id, "email": u.email})
            else:
                started.append({**out, "user_id": u.id, "email": u.email})
        return {
            "tick": "multi_tenant",
            "started": len(started),
            "skipped": len(skipped),
            "items_started": started[:50],
            "items_skipped": skipped[:50],
        }

    # Single-tenant: open env/memory repo without a user session
    from backend.api import deps as deps_mod
    from backend.sheets.google_sheets import build_repository_from_settings
    from backend.sheets.repository import InMemorySheetsRepository

    if deps_mod._use_memory_repo(settings):
        if deps_mod._DEV_MEMORY_REPO is None:
            deps_mod._DEV_MEMORY_REPO = InMemorySheetsRepository()
        repo = deps_mod._DEV_MEMORY_REPO
    else:
        if not settings.spreadsheet_id:
            raise HTTPException(
                status_code=503, detail="SPREADSHEET_ID is not configured"
            )
        try:
            repo = build_repository_from_settings(settings, user_credentials=None)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail=f"Google Sheets unavailable: {exc}"
            ) from exc

    out = start_known_job("fx-full", repo, params={}, tenant_id=None)
    if out.get("status") == "rejected":
        return {**out, "tick": "skipped"}
    return {**out, "tick": "started"}


@router.post("/jobs/{kind}")
async def jobs_start(
    kind: str,
    repo: RepoDep,
    user: UserDep,
    settings: SettingsDep,
    body: JobStartBody | None = None,
) -> dict[str, Any]:
    """Start a known background job by kind (e.g. fx-full, fx-fetch-cnb)."""
    if kind == "tick":
        raise HTTPException(
            status_code=400,
            detail="use POST /admin/jobs/tick with X-Cron-Secret",
        )
    params: dict[str, Any] = {}
    if body:
        if body.date_from:
            params["date_from"] = body.date_from
        if body.date_to:
            params["date_to"] = body.date_to
        if body.limit is not None:
            params["limit"] = body.limit
        if body.max_passes is not None:
            params["max_passes"] = body.max_passes
    tenant = user.user_id if settings.multi_tenant else None
    out = start_known_job(kind, repo, params=params, tenant_id=tenant)
    if out.get("status") == "rejected":
        status = 400 if "unknown" in str(out.get("error", "")).lower() else 409
        raise HTTPException(status_code=status, detail=out.get("error") or "rejected")
    return out


@router.get("/jobs/{job_id}")
async def jobs_get(
    job_id: str,
    user: UserDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    tenant = user.user_id if settings.multi_tenant else None
    job = get_job(job_id, tenant_id=tenant)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
