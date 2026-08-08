"""Admin / maintenance endpoints (cleanup, warm cache, FX backfill, CNB, jobs)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import RepoDep, SettingsDep, UserDep, clear_repo_cache
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

router = APIRouter(prefix="/admin", tags=["admin"])


class CleanupRequest(BaseModel):
    scopes: list[str] = Field(..., min_length=1, description="Scope ids to clear")
    confirm: str = Field(
        ...,
        description=f'Must be exactly "{CONFIRM_TOKEN}" to proceed',
    )


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
    clear_repo_cache()
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
    _user: UserDep,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    return {
        "items": list_jobs(limit=limit),
        "kinds": sorted(KIND_RUNNERS.keys()),
    }


@router.post("/jobs/tick")
async def jobs_tick(
    repo: RepoDep,
    settings: SettingsDep,
    x_cron_secret: str | None = Header(default=None, alias="X-Cron-Secret"),
) -> dict[str, Any]:
    """
    Cron entrypoint: run fx-full when CRON_SECRET matches.

    Railway cron: POST /api/admin/jobs/tick with header X-Cron-Secret.
    """
    expected = (settings.cron_secret or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET not configured",
        )
    if not x_cron_secret or x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="invalid cron secret")

    out = start_known_job("fx-full", repo, params={})
    if out.get("status") == "rejected":
        return {**out, "tick": "skipped"}
    return {**out, "tick": "started"}


@router.post("/jobs/{kind}")
async def jobs_start(
    kind: str,
    repo: RepoDep,
    _user: UserDep,
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
    out = start_known_job(kind, repo, params=params)
    if out.get("status") == "rejected":
        status = 400 if "unknown" in str(out.get("error", "")).lower() else 409
        raise HTTPException(status_code=status, detail=out.get("error") or "rejected")
    return out


@router.get("/jobs/{job_id}")
async def jobs_get(job_id: str, _user: UserDep) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
