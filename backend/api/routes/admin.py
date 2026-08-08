"""Admin / maintenance endpoints (cleanup, warm cache, FX backfill, CNB)."""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import RepoDep, UserDep, clear_repo_cache
from backend.services.cleanup import (
    CONFIRM_TOKEN,
    list_scopes,
    preview_cleanup,
    result_to_dict,
    run_cleanup,
)
from backend.services.maintenance import (
    backfill_amount_usd,
    fetch_cnb_range,
    warm_cache,
)
from backend.services.response_cache import cache_invalidate

router = APIRouter(prefix="/admin", tags=["admin"])

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


class CleanupRequest(BaseModel):
    scopes: list[str] = Field(..., min_length=1, description="Scope ids to clear")
    confirm: str = Field(
        ...,
        description=f'Must be exactly "{CONFIRM_TOKEN}" to proceed',
    )


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

    job_id = str(uuid.uuid4())
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": "backfill-fx",
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "result": None,
            "error": None,
        }

    def _run() -> None:
        try:
            result = backfill_amount_usd(repo, limit=limit)
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "done"
                _JOBS[job_id]["result"] = result
                _JOBS[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:  # noqa: BLE001
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "error"
                _JOBS[job_id]["error"] = str(exc)
                _JOBS[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@router.post("/fetch-cnb")
async def fetch_cnb_endpoint(
    repo: RepoDep,
    _user: UserDep,
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> dict[str, Any]:
    """Fetch CNB daily rates for a date range and upsert FXRates."""
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to must be >= date_from")
    if (date_to - date_from).days > 400:
        raise HTTPException(status_code=400, detail="range max 400 days")
    return fetch_cnb_range(repo, date_from=date_from, date_to=date_to)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, _user: UserDep) -> dict[str, Any]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
